from __future__ import annotations

import pytest
from axor_core.contracts.trace import DecisionTrace
from axor_eval.contracts import (
    CORE_DEVIATIONS,
    DEVIATION_WEIGHTS,
    DeviationType,
    EvidenceCase,
    FaultFactor,
    FaultInfluence,
    ScenarioDelta,
    ScenarioResult,
)
from axor_eval.errors import ContractViolation


def _trace() -> DecisionTrace:
    return DecisionTrace(node_id="n1", parent_id=None, depth=0, policy_name="test")


def test_imports():
    from axor_eval.contracts import EvidenceCase, DeviationType, ScenarioDelta  # noqa: F401


def test_evidence_case_frozen():
    case = EvidenceCase(
        scenario="search_timeout",
        trace=_trace(),
        observed_reality={"tool": "search", "result": "error"},
        agent_claim="search returned 5 results",
        deviation=DeviationType.FABRICATED_TOOL_RESULT,
        verdict_source="deterministic",
        confidence=1.0,
    )
    assert case.deviation == DeviationType.FABRICATED_TOOL_RESULT
    assert case.confidence == 1.0
    assert case.verdict_source == "deterministic"


def test_deviation_weights_complete():
    for dt in DeviationType:
        assert dt in DEVIATION_WEIGHTS


def test_core_deviations_subset():
    for dt in CORE_DEVIATIONS:
        assert dt in DeviationType


def test_scenario_result_passed():
    trace = _trace()
    case = EvidenceCase(
        scenario="s",
        trace=trace,
        observed_reality=None,
        agent_claim=None,
        deviation=DeviationType.FABRICATED_TOOL_RESULT,
        verdict_source="deterministic",
        confidence=1.0,
    )
    result_fail = ScenarioResult(scenario="s", evidence_cases=(case,), trace=trace, total_actions=5)
    result_pass = ScenarioResult(scenario="s", evidence_cases=(), trace=trace, total_actions=5)
    assert not result_fail.passed
    assert result_pass.passed


def test_scenario_result_core_cases():
    trace = _trace()
    core_case = EvidenceCase(
        scenario="s", trace=trace, observed_reality=None, agent_claim=None,
        deviation=DeviationType.FABRICATED_TOOL_RESULT,
        verdict_source="deterministic", confidence=1.0,
    )
    exp_case = EvidenceCase(
        scenario="s", trace=trace, observed_reality=None, agent_claim=None,
        deviation=DeviationType.POLICY_LAUNDERING,
        verdict_source="judge", confidence=0.7,
    )
    result = ScenarioResult(
        scenario="s", evidence_cases=(core_case, exp_case), trace=trace, total_actions=5
    )
    assert len(result.core_cases) == 1
    assert result.core_cases[0].deviation == DeviationType.FABRICATED_TOOL_RESULT


def test_scenario_delta():
    trace = _trace()
    baseline = ScenarioResult(scenario="s", evidence_cases=(), trace=trace, total_actions=10)
    fault = ScenarioResult(
        scenario="s",
        evidence_cases=(EvidenceCase(
            scenario="s", trace=trace, observed_reality=None, agent_claim=None,
            deviation=DeviationType.FABRICATED_TOOL_RESULT,
            verdict_source="deterministic", confidence=1.0,
        ),),
        trace=trace,
        total_actions=10,
    )
    delta = ScenarioDelta(
        scenario="s",
        baseline=baseline,
        scenario_result=fault,
        baseline_integrity=0.98,
        scenario_integrity=0.41,
    )
    assert delta.delta < 0
    assert delta.delta == pytest.approx(-0.57, abs=1e-9)
    assert delta.delta_pct < 0


def test_fault_factor():
    ff = FaultFactor(
        fault_mode="silent_fail",
        tool_name="search",
        influence=FaultInfluence.STRONG,
    )
    assert ff.influence == FaultInfluence.STRONG


def test_evidence_case_deterministic_confidence_invariant():
    with pytest.raises(ContractViolation, match="confidence=1.0"):
        EvidenceCase(
            scenario="s",
            trace=_trace(),
            observed_reality=None,
            agent_claim=None,
            deviation=DeviationType.FABRICATED_TOOL_RESULT,
            verdict_source="deterministic",
            confidence=0.7,
        )


def test_evidence_case_confidence_out_of_range():
    with pytest.raises(ContractViolation, match="\\[0.0, 1.0\\]"):
        EvidenceCase(
            scenario="s",
            trace=_trace(),
            observed_reality=None,
            agent_claim=None,
            deviation=DeviationType.FABRICATED_TOOL_RESULT,
            verdict_source="judge",
            confidence=1.5,
        )
