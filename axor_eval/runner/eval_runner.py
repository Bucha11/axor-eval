from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from axor_core.budget.tracker import BudgetTracker
from axor_core.contracts.trace import DecisionTrace
from axor_core.degradation.engine import DegradationEngine
from axor_core.contracts.mode import ExecutionMode
from axor_core.trace.collector import TraceCollector

from axor_eval.audit.budget_audit import BudgetAuditLayer
from axor_eval.audit.tool_audit import ToolAuditLayer
from axor_eval.contracts import EvidenceCase, ScenarioResult
from axor_eval.deprivation.engine import ToolDeprivationEngine
from axor_eval.replay.recorder import ReplayRecorder

# Signature: agent_fn(tools: dict[str, Callable]) → str (agent output text)
AgentFn = Callable[[dict[str, Any]], str]


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

    Wires:
      - ExecutionMode.OBSERVE (via DegradationEngine.from_mode)
      - ToolDeprivationEngine
      - TraceCollector
      - ReplayRecorder (optional)
      - ToolAuditLayer + BudgetAuditLayer

    Usage::

        spec = FaultSpec().add("search", "silent_fail")
        runner = EvalRunner()
        result = runner.run_scenario(
            scenario_id="search_timeout",
            agent_fn=my_agent,
            tools={"search": real_search_fn},
            faults=spec,
        )
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
        # Wire observe mode — DegradationEngine won't block the agent.
        degradation_engine = DegradationEngine.from_mode(
            ExecutionMode.OBSERVE, node_id=scenario_id
        )

        # Set up deprivation.
        deprivation = ToolDeprivationEngine(seed=self._seed)
        if faults:
            for tool_name, mode in faults.rules:
                deprivation.register(tool_name, mode)

        # Wrap tools with deprivation.
        wrapped_tools = deprivation.wrap_all(tools)

        # Set up budget tracker and trace collector.
        budget_tracker = BudgetTracker()
        budget_tracker.register_node(scenario_id, None, 0)
        trace_collector = TraceCollector(session_id=scenario_id)
        trace_collector.register_node(scenario_id, None, 0, policy_name="eval")

        # Set up replay recording if requested.
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
            agent_output = agent_fn(wrapped_tools)
        finally:
            if recorder is not None:
                recorder.close()

        # Flush trace events from degradation engine.
        for event in degradation_engine.drain_events():
            trace_collector.record(event)

        trace = trace_collector.get_trace(scenario_id) or DecisionTrace(
            node_id=scenario_id, parent_id=None, depth=0, policy_name="eval"
        )

        # Audit: tool + budget.
        fault_log = deprivation.fault_log
        total_actions = len(fault_log) + len(tools)

        tool_cases: list[EvidenceCase] = ToolAuditLayer().analyze(
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
        )

        all_cases = tuple(tool_cases + budget_cases)
        return ScenarioResult(
            scenario=scenario_id,
            evidence_cases=all_cases,
            trace=trace,
            total_actions=total_actions,
        )
