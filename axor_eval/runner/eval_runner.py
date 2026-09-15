from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from axor_core.budget.tracker import BudgetTracker
from axor_core.contracts.mode import ExecutionMode
from axor_core.contracts.trace import DecisionTrace
from axor_core.degradation.engine import DegradationEngine
from axor_wrap import ENFORCEMENT_OFF, WrappedToolset, harness_manifest

from axor_eval.audit.budget_audit import BudgetAuditLayer
from axor_eval.audit.retrieval_audit import RetrievalAuditLayer
from axor_eval.audit.tool_audit import ToolAuditLayer
from axor_eval.compatibility import warn_once_on_skew
from axor_eval.contracts import AgentClaims, AgentResult, EvidenceCase, ScenarioResult
from axor_eval.deprivation.engine import ToolDeprivationEngine
from axor_eval.replay.recorder import ReplayRecorder

# Signature: agent_fn(tools: dict[str, Callable]) → str | AgentResult.
# Returning an AgentResult lets the agent attach structured claims, which makes
# claim-based audits deterministic; a bare str falls back to heuristic detection.
AgentFn = Callable[[dict[str, Any]], "str | AgentResult"]

# Deterministic per-tool-call token cost recorded as governance telemetry. The
# eval agent is not an LLM, so there is no model-reported usage — these are the
# observed costs the budget subsystem attributes to each governed tool call, and
# they are what BUDGET_MISREPORT compares an agent's token claim against.
_OBS_INPUT_TOKENS = 100
_OBS_OUTPUT_TOKENS = 50
_OBS_TOOL_TOKENS = 10


class FaultSpec:
    """Declares which tools to deprive and how."""

    def __init__(self) -> None:
        self._rules: list[tuple[str, str]] = []

    def add(self, tool_name: str, mode: str) -> FaultSpec:
        self._rules.append((tool_name, mode))
        return self

    @property
    def rules(self) -> list[tuple[str, str]]:
        return list(self._rules)


class EvalRunner:
    """
    Orchestrates a single scenario evaluation run (§15 MVP).

    The agent runs through the ONE wrap with governance observed but not
    enforced. There is no eval-specific gate: ``run_scenario`` builds an
    ``axor_wrap.WrappedToolset`` with ``enforcement="off"`` and
    ``run_governed`` drives an ``axor_core.GovernedSession`` in
    ``ExecutionMode.OBSERVE`` — the same idea at two layers, for the two kinds
    of agent (one that is handed a tool dict, one the kernel drives). Either
    way the governor evaluates every call, records every verdict, and registers
    every output in the per-value taint ledger; only the block is skipped, so
    measurement is not contaminated by enforcement.

    That is deliberately the same code the Control Plane and axor-lab run: an
    eval trace and a production trace of the same run are then comparable,
    which they were not while this class kept its own instrumentation.

    Three layers, in order:
      - BELOW the wrap — ToolDeprivationEngine substitutes tool callables
        (fault injection). A substituted callable is still just a callable.
      - THE WRAP — WrappedToolset(enforcement="off") / GovernedSession(OBSERVE).
        Verdicts, taint and trace events come from axor-core.
      - ABOVE the wrap — ToolAuditLayer + RetrievalAuditLayer + BudgetAuditLayer
        compare the injected ground truth (``fault_log``) against what the agent
        claimed. The fault log stays separate from the trace on purpose: it is
        the oracle, and deriving it from the observation would be deriving the
        oracle from the thing under test.

    Also wired: DegradationEngine.from_mode(OBSERVE), a BudgetTracker charged
    per call (the eval agent is not an LLM, so there is no model-reported usage
    for BUDGET_MISREPORT to check a claim against), and an optional
    ReplayRecorder.

    Usage::

        spec = FaultSpec().add("search", "silent_fail")
        runner = EvalRunner()
        result = runner.run_scenario("search_timeout", my_agent, {"search": fn}, faults=spec)

    Tool calls are keyword-only: the kernel gates on argument names.
    """

    def __init__(
        self,
        seed: str = "axor_eval",
        replay_dir: Path | None = None,
        budget_tolerance: float = 0.20,
    ) -> None:
        # Warn-only, once per process: makes core version skew visible at the
        # place it bites (deep core API usage below) instead of at first crash.
        warn_once_on_skew()
        self._seed = seed
        self._replay_dir = replay_dir
        self._budget_tolerance = budget_tolerance

    def run_scenario(
        self,
        scenario_id: str,
        agent_fn: AgentFn,
        tools: dict[str, Any],
        faults: FaultSpec | None = None,
        env_config: dict[str, Any] | None = None,
        manifests: list[dict[str, Any]] | None = None,
    ) -> ScenarioResult:
        # Observe mode — governance subsystems record but never block the agent.
        degradation_engine = DegradationEngine.from_mode(
            ExecutionMode.OBSERVE, node_id=scenario_id
        )

        # Fault injection sits BELOW the wrap: it substitutes tool callables, and
        # a substituted callable is still just a callable. So the governed view
        # is of the world the agent actually got, faults included.
        deprivation = ToolDeprivationEngine(seed=self._seed)
        if faults:
            for tool_name, mode in faults.rules:
                deprivation.register(tool_name, mode)
        wrapped_tools = deprivation.wrap_all(tools)

        # One wrap, observing. `enforcement="off"` is axor-wrap's bypass flag and
        # the exact analogue of ExecutionMode.OBSERVE on the streaming path: the
        # governor still evaluates every call, still records every verdict, and
        # still registers every output in the per-value taint ledger — only the
        # block is skipped, so measurement is not contaminated by enforcement.
        toolset = WrappedToolset(
            wrapped_tools,
            manifests if manifests is not None else harness_manifests(wrapped_tools),
            enforcement=ENFORCEMENT_OFF,
            # no raw-value retention: no audit layer reads a trace's value
            # ledger, and replay is recorded from the deprivation engine below.
            # Turning it on would keep every tool result in memory for nothing.
            record=False,
            node_id=scenario_id,
        )

        budget_tracker = BudgetTracker()
        budget_tracker.register_node(scenario_id, None, 0)
        action_count = {"n": 0}

        # Token accounting only. Everything governance-shaped — the verdict, the
        # trace event, the taint root — now comes from the kernel through the
        # wrap; this shim exists because the eval agent is not an LLM and there
        # is no model-reported usage to read, so BUDGET_MISREPORT needs an
        # attributed cost per call from somewhere.
        def _metered(name: str, fn: Callable) -> Callable:
            @functools.wraps(fn)
            def _charged(*args: Any, **kwargs: Any) -> Any:
                if args:
                    # the kernel gates on argument NAMES (driving_args,
                    # value_policies, per-arg provenance); a positional value
                    # has no name to gate on, so the wrap is keyword-only and
                    # says so here rather than through the wrapper's arity.
                    raise TypeError(
                        f"governed tool {name!r} was called with positional "
                        "arguments; a governed tool call must be keyword-only"
                    )
                budget_tracker.record(
                    scenario_id,
                    input_tokens=_OBS_INPUT_TOKENS,
                    output_tokens=_OBS_OUTPUT_TOKENS,
                    tool_tokens=_OBS_TOOL_TOKENS,
                )
                action_count["n"] += 1
                return fn(*args, **kwargs)

            return _charged

        governed_tools = {
            name: _metered(name, fn) for name, fn in toolset.callables().items()
        }

        # Optional replay recording.
        recorder: ReplayRecorder | None = None
        if self._replay_dir is not None:
            replay_path = self._replay_dir / f"{scenario_id}.jsonl"
            recorder = ReplayRecorder(
                output_path=replay_path,
                scenario_id=scenario_id,
                engine=deprivation,
                env_config=env_config,
            )

        try:
            raw = agent_fn(governed_tools)
        finally:
            if recorder is not None:
                recorder.close()

        agent_output, claims = _split_agent_output(raw)

        # The kernel's own events for this session, plus the degradation engine's.
        # There is no second instrumentation path here any more: the verdicts and
        # the taint roots are the governor's, produced by the same code the
        # Control Plane and axor-lab run.
        trace = DecisionTrace(
            node_id=scenario_id, parent_id=None, depth=0, policy_name="eval",
            events=list(toolset.trace_events),  # type: ignore[arg-type]
        )
        for event in degradation_engine.drain_events():
            trace.events.append(event)

        fault_log = deprivation.fault_log
        # Total actions = governed tool calls actually observed (real action count).
        total_actions = max(action_count["n"], len(fault_log))

        tool_cases: list[EvidenceCase] = ToolAuditLayer().analyze(
            trace=trace,
            fault_log=fault_log,
            agent_output=agent_output,
            scenario=scenario_id,
            claims=claims,
        )
        retrieval_cases: list[EvidenceCase] = RetrievalAuditLayer().analyze(
            trace=trace,
            fault_log=fault_log,
            agent_output=agent_output,
            scenario=scenario_id,
        )
        budget_cases: list[EvidenceCase] = BudgetAuditLayer(
            tolerance=self._budget_tolerance
        ).analyze(
            budget_snapshot=budget_tracker.snapshot(),
            agent_output=agent_output,
            trace=trace,
            scenario=scenario_id,
            claims=claims,
        )

        all_cases = tuple(tool_cases + retrieval_cases + budget_cases)
        return ScenarioResult(
            scenario=scenario_id,
            evidence_cases=all_cases,
            trace=trace,
            total_actions=total_actions,
        )


    async def run_governed(
        self,
        scenario_id: str,
        behavior: Callable[[list], Any],
        tools: dict[str, Any],
        faults: FaultSpec | None = None,
        policy: Any = None,
        usage: dict[str, int] | None = None,
    ) -> ScenarioResult:
        """
        Governed (streaming) scenario: drive a reactive agent through a real
        GovernedSession in OBSERVE mode.

        `behavior(history) -> CallTool | Finish` (see axor_eval.governed). Each tool
        call is intercepted by the real IntentLoop — policy/taint/degradation are
        resolved and recorded, nothing is blocked — executed via a
        CapabilityExecutor, and the real (fault-injected) result is fed back to the
        agent. The DecisionTrace and token totals are produced by axor-core itself.

        When `policy` is None the harness composes one that grants exactly the
        tools it was handed. Core's default policy is fail-closed on tool names it
        was never told about, and it is right to be — but denying them here would
        measure the policy gate rather than execution integrity under faults, which
        is the thing eval exists to measure. Pass an explicit `policy` to audit a
        real deployment's ceiling instead.
        """
        from axor_core import GovernedSession
        from axor_core.capability.executor import CapabilityExecutor
        from axor_core.contracts.mode import ExecutionMode

        from axor_eval.governed import ReactiveAgent, ToolHandlerAdapter

        deprivation = ToolDeprivationEngine(seed=self._seed)
        if faults:
            for tool_name, mode in faults.rules:
                deprivation.register(tool_name, mode)
        wrapped_tools = deprivation.wrap_all(tools)

        cap = CapabilityExecutor()
        for name, fn in wrapped_tools.items():
            cap.register(ToolHandlerAdapter(name, fn))

        if policy is None:
            policy = _harness_policy(wrapped_tools)

        agent = ReactiveAgent(behavior, usage=usage)
        session = GovernedSession(
            executor=agent,
            capability_executor=cap,
            mode=ExecutionMode.OBSERVE,
        )
        try:
            exec_result = await session.run(scenario_id, policy=policy)
        finally:
            await session.aclose()

        # Real telemetry produced by axor-core.
        traces = session.all_traces()
        node_traces = [t for t in traces if t.node_id != session.session_id()]
        trace = node_traces[-1] if node_traces else (traces[-1] if traces else DecisionTrace(
            node_id=scenario_id, parent_id=None, depth=0, policy_name="eval"
        ))
        actual_tokens = session.total_tokens_spent()

        final = agent.result
        claims = final.claims if final is not None else None
        agent_output = exec_result.output

        fault_log = deprivation.fault_log
        approved = sum(1 for e in trace.events if e.kind.value == "intent_approved")
        total_actions = max(approved, len(fault_log))

        tool_cases = ToolAuditLayer().analyze(
            trace=trace, fault_log=fault_log, agent_output=agent_output,
            scenario=scenario_id, claims=claims,
        )
        retrieval_cases = RetrievalAuditLayer().analyze(
            trace=trace, fault_log=fault_log, agent_output=agent_output, scenario=scenario_id,
        )
        budget_cases = BudgetAuditLayer(tolerance=self._budget_tolerance).analyze(
            budget_snapshot={}, agent_output=agent_output, trace=trace,
            scenario=scenario_id, claims=claims, actual_tokens=actual_tokens,
        )

        return ScenarioResult(
            scenario=scenario_id,
            evidence_cases=tuple(tool_cases + retrieval_cases + budget_cases),
            trace=trace,
            total_actions=total_actions,
        )


def _harness_policy(tools: dict[str, Any]) -> Any:
    """The default policy for a governed scenario: grant exactly `tools`.

    Named ``eval_harness`` so it is obvious in a trace that the ceiling came from
    the harness and not from a deployment. Everything outside the registered tool
    names stays denied — a scenario that reaches for a tool it never registered is
    still a real denial, which is what makes the audit layers meaningful.
    """
    from axor_core.contracts.policy import ExecutionPolicy, ToolPolicy

    return ExecutionPolicy(
        name="eval_harness",
        tool_policy=ToolPolicy(extra_allowed=tuple(sorted(tools))),
    )


def _split_agent_output(raw: str | AgentResult) -> tuple[str, AgentClaims | None]:
    """Normalise an agent return value into (text, claims)."""
    if isinstance(raw, AgentResult):
        return raw.text, raw.claims
    return str(raw), None


def harness_manifests(tools: dict[str, Any]) -> list[dict[str, Any]]:
    """The default tool contract for a scenario: every tool an untrusted READ.

    Untrusted because that is eval's premise — a tool's return is exactly the
    surface fault injection makes adversarial, so the kernel should taint it.
    No egress sinks and no value policies: a harness that declared one would be
    measuring the policy gate rather than execution integrity under faults,
    which is the thing eval exists to measure. Same reasoning as
    ``_harness_policy`` on the streaming path.

    Pass explicit ``manifests`` to ``run_scenario`` to audit a real deployment's
    contract instead — then the run records real denials (still unblocked, since
    the wrap runs with enforcement off).
    """
    return [harness_manifest(name, untrusted=True) for name in sorted(tools)]
