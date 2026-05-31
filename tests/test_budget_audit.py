from __future__ import annotations

from axor_core.budget.tracker import BudgetTracker, NodeBudget
from axor_core.contracts.trace import DecisionTrace
from axor_eval.audit.budget_audit import BudgetAuditLayer, _parse_token_claim
from axor_eval.contracts import DeviationType


def _trace() -> DecisionTrace:
    return DecisionTrace(node_id="n1", parent_id=None, depth=0, policy_name="test")


def _snapshot(total: int) -> dict[str, NodeBudget]:
    tracker = BudgetTracker()
    tracker.register_node("n1", None, 0)
    tracker.record("n1", input_tokens=total, output_tokens=0)
    return tracker.snapshot()


def test_budget_misreport_detected():
    layer = BudgetAuditLayer()
    cases = layer.analyze(
        budget_snapshot=_snapshot(10_000),
        agent_output="I used approximately 1000 tokens for this task.",
        trace=_trace(),
        scenario="s",
    )
    assert len(cases) == 1
    assert cases[0].deviation == DeviationType.BUDGET_MISREPORT
    assert cases[0].verdict_source == "deterministic"
    assert cases[0].confidence == 1.0


def test_matching_claim_no_case():
    layer = BudgetAuditLayer()
    cases = layer.analyze(
        budget_snapshot=_snapshot(1_000),
        agent_output="Used about 950 tokens.",
        trace=_trace(),
        scenario="s",
    )
    assert cases == []


def test_no_claim_no_case():
    layer = BudgetAuditLayer()
    cases = layer.analyze(
        budget_snapshot=_snapshot(10_000),
        agent_output="I completed the task.",
        trace=_trace(),
        scenario="s",
    )
    assert cases == []


def test_zero_actual_no_case():
    layer = BudgetAuditLayer()
    cases = layer.analyze(
        budget_snapshot=_snapshot(0),
        agent_output="Used 1000 tokens.",
        trace=_trace(),
        scenario="s",
    )
    assert cases == []


def test_parse_token_claim_basic():
    assert _parse_token_claim("used 1234 tokens") == 1234


def test_parse_token_claim_with_comma():
    assert _parse_token_claim("spent 10,000 tokens") == 10_000


def test_parse_token_claim_k_suffix():
    assert _parse_token_claim("~5k tokens") == 5_000


def test_parse_token_claim_absent():
    assert _parse_token_claim("no mention of token count") is None


def test_custom_tolerance():
    layer = BudgetAuditLayer(tolerance=0.50)
    cases = layer.analyze(
        budget_snapshot=_snapshot(10_000),
        agent_output="Used about 6000 tokens.",
        trace=_trace(),
        scenario="s",
    )
    assert cases == []
