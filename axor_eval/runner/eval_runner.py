from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from axor_core.budget.tracker import BudgetTracker
from axor_core.contracts.mode import ExecutionMode
from axor_core.contracts.taint import TaintScope, TaintSource
from axor_core.contracts.trace import DecisionTrace, TraceEvent, TraceEventKind
from axor_core.degradation.engine import DegradationEngine
from axor_core.taint.engine import TaintEngine
from axor_core.trace.collector import TraceCollector

from axor_eval.audit.budget_audit import BudgetAuditLayer
from axor_eval.audit.retrieval_audit import RetrievalAuditLayer
from axor_eval.audit.tool_audit import ToolAuditLayer
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

    def add(self, tool_name: str, mode: str) -> "FaultSpec":
        self._rules.append((tool_name, mode))
        return self

    @property
    def rules(self) -> list[tuple[str, str]]:
        return list(self._rules)


class EvalRunner:
    """
    Orchestrates a single scenario evaluation run (§15 MVP).

    The agent runs under axor-core's governance observation subsystems in
    ExecutionMode.OBSERVE: every governed tool call is recorded by a real
    TraceCollector (INTENT_APPROVED), charged to a real BudgetTracker, and routed
    through a real TaintEngine (external tool surface → taint). Nothing is
    denied/locked — OBSERVE keeps the agent unblocked so measurement is not
    contaminated by enforcement. The result is a populated DecisionTrace and real
    token telemetry that the audit layers verify against.

    Wires:
      - DegradationEngine.from_mode(OBSERVE)
      - ToolDeprivationEngine (fault injection)
      - TaintEngine + BudgetTracker + TraceCollector (real telemetry)
      - ReplayRecorder (optional)
      - ToolAuditLayer + RetrievalAuditLayer + BudgetAuditLayer

    Usage::

        spec = FaultSpec().add("search", "silent_fail")
        runner = EvalRunner()
        result = runner.run_scenario("search_timeout", my_agent, {"search": fn}, faults=spec)
    """

    def __init__(
        self,
        seed: str = "axor_eval",
        replay_dir: Path | None = None,
        budget_tolerance: float = 0.20,
    ) -> None:
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
    ) -> ScenarioResult:
        # Observe mode — governance subsystems record but never block the agent.
        degradation_engine = DegradationEngine.from_mode(
            ExecutionMode.OBSERVE, node_id=scenario_id
        )

        # Fault injection setup.
        deprivation = ToolDeprivationEngine(seed=self._seed)
        if faults:
            for tool_name, mode in faults.rules:
                deprivation.register(tool_name, mode)
        wrapped_tools = deprivation.wrap_all(tools)

        # Real governance telemetry: trace + budget + taint.
        budget_tracker = BudgetTracker()
        budget_tracker.register_node(scenario_id, None, 0)
        trace_collector = TraceCollector(session_id=scenario_id)
        trace_collector.register_node(scenario_id, None, 0, policy_name="eval")
        taint_engine = TaintEngine(node_id=scenario_id)

        action_count = {"n": 0}

        def _govern(tool_name: str, fn: Callable) -> Callable:
            def _observed(*args: Any, **kwargs: Any) -> Any:
                # INTENT_APPROVED trace event (OBSERVE never denies).
                trace_collector.record(TraceEvent(
                    kind=TraceEventKind.INTENT_APPROVED,
                    node_id=scenario_id,
                    sequence=action_count["n"],
                    payload={"tool": tool_name, "args": _safe_args(args, kwargs)},
                ))
                # Real budget telemetry for this governed call.
                budget_tracker.record(
                    scenario_id,
                    input_tokens=_OBS_INPUT_TOKENS,
                    output_tokens=_OBS_OUTPUT_TOKENS,
                    tool_tokens=_OBS_TOOL_TOKENS,
                )
                # External tool surface → taint (drained into the trace below).
                taint_engine.propagate(TaintSource.MCP, TaintScope.SESSION)
                action_count["n"] += 1
                return fn(*args, **kwargs)

            return _observed

        governed_tools = {name: _govern(name, fn) for name, fn in wrapped_tools.items()}

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

        # Drain taint + degradation events into the trace.
        for event in taint_engine.drain_events():
            trace_collector.record(event)
        for event in degradation_engine.drain_events():
            trace_collector.record(event)

        trace = trace_collector.get_trace(scenario_id) or DecisionTrace(
            node_id=scenario_id, parent_id=None, depth=0, policy_name="eval"
        )

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
        behavior: "Callable[[list], Any]",
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


def _split_agent_output(raw: "str | AgentResult") -> tuple[str, "AgentClaims | None"]:
    """Normalise an agent return value into (text, claims)."""
    if isinstance(raw, AgentResult):
        return raw.text, raw.claims
    return str(raw), None


def _safe_args(args: tuple, kwargs: dict) -> dict[str, Any]:
    """Best-effort, serialisable rendering of tool call args for the trace."""
    out: dict[str, Any] = {}
    if args:
        out["positional"] = [repr(a) for a in args]
    if kwargs:
        out["kwargs"] = {k: repr(v) for k, v in kwargs.items()}
    return out
