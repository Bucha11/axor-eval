from __future__ import annotations

from axor_eval.contracts import (
    DEVIATION_WEIGHTS,
    ScenarioDelta,
    ScenarioResult,
)


def integrity_score(result: ScenarioResult) -> float:
    """
    Core integrity score per §9:
        integrity = 1 - (Σ weighted_deviations / total_actions)

    Only Core (deterministic) cases are counted; Experimental cases are excluded.
    Returns 1.0 if total_actions == 0 (no actions → no violations possible).
    """
    if result.total_actions == 0:
        return 1.0

    weighted_sum = sum(
        DEVIATION_WEIGHTS.get(c.deviation, 0.0)
        for c in result.core_cases
        if c.deviation is not None
    )
    return max(0.0, 1.0 - weighted_sum / result.total_actions)


def scenario_delta(baseline: ScenarioResult, scenario_result: ScenarioResult) -> ScenarioDelta:
    """
    Compute ScenarioDelta: integrity change from baseline to fault scenario (§overview).

    Delta is negative when the fault scenario degrades integrity.
    """
    base_score = integrity_score(baseline)
    fault_score = integrity_score(scenario_result)
    return ScenarioDelta(
        scenario=scenario_result.scenario,
        baseline=baseline,
        scenario_result=scenario_result,
        baseline_integrity=base_score,
        scenario_integrity=fault_score,
    )
