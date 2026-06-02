from __future__ import annotations

import importlib.util

import pytest

from axor_eval.audit.behavioral_audit import BehavioralIntegrityAudit
from axor_eval.contracts import DeviationType, ScenarioResult
from axor_eval.runner.scoring import integrity_score


def _payload(verdict: str, score: float = 0.8, longitudinal: float = 0.6,
             calibration: str = "CALIBRATED", probes: int = 5) -> dict:
    return {
        "session_id": "sess1",
        "agent_id": "agent1",
        "overall_verdict": verdict,
        "max_drift_score": score,
        "longitudinal_signal": longitudinal,
        "calibration_status": calibration,
        "probes_sent": probes,
    }


async def test_drift_detected_emits_case():
    audit = BehavioralIntegrityAudit()
    await audit.feed(_payload("DRIFT_DETECTED"))
    cases = audit.cases()
    assert len(cases) == 1
    assert cases[0].deviation == DeviationType.BEHAVIORAL_DRIFT
    assert cases[0].verdict_source == "judge"
    assert 0.0 < cases[0].confidence < 1.0


async def test_consistency_anomaly_emits_case():
    audit = BehavioralIntegrityAudit()
    await audit.feed(_payload("CONSISTENCY_ANOMALY"))
    assert len(audit.cases()) == 1


@pytest.mark.parametrize("verdict", ["CONSISTENT", "INCONCLUSIVE", "WHATEVER"])
async def test_non_drift_verdicts_no_case(verdict):
    audit = BehavioralIntegrityAudit()
    await audit.feed(_payload(verdict))
    assert audit.cases() == []


def test_confidence_never_reaches_one_even_at_max_score():
    audit = BehavioralIntegrityAudit()
    case = audit.evaluate(_payload("DRIFT_DETECTED", score=1.0, longitudinal=1.0))
    assert case is not None
    assert case.confidence < 1.0


def test_uncalibrated_is_discounted():
    audit = BehavioralIntegrityAudit()
    cal = audit.evaluate(_payload("DRIFT_DETECTED", score=0.8, calibration="CALIBRATED"))
    unc = audit.evaluate(_payload("DRIFT_DETECTED", score=0.8, calibration="UNCALIBRATED"))
    assert unc.confidence < cal.confidence


def test_behavioral_drift_excluded_from_headline():
    # Experimental + judge verdict → never counted in the integrity score.
    audit = BehavioralIntegrityAudit()
    case = audit.evaluate(_payload("DRIFT_DETECTED"))
    result = ScenarioResult(
        scenario="s", evidence_cases=(case,), trace=case.trace, total_actions=4,
    )
    assert result.core_cases == ()
    assert integrity_score(result) == 1.0


def test_cases_drains_buffer():
    audit = BehavioralIntegrityAudit()
    audit.evaluate(_payload("DRIFT_DETECTED"))  # evaluate() does not buffer
    assert audit.cases() == []


@pytest.mark.skipif(
    importlib.util.find_spec("axor_probe") is None,
    reason="axor-probe not installed",
)
async def test_wire_compatible_with_probe_feed_audit():
    # Prove the bridge end-to-end: axor-probe's feed_audit pushes into our sink
    # without either package importing the other.
    from types import SimpleNamespace

    from axor_probe.integration.eval import feed_audit

    report = SimpleNamespace(
        session_id="s", agent_id="a", overall_verdict="DRIFT_DETECTED",
        max_drift_score=0.7, longitudinal_signal=0.5,
        calibration_status="CALIBRATED", probes_sent=4,
    )
    audit = BehavioralIntegrityAudit()
    await feed_audit(report, audit.feed)
    cases = audit.cases()
    assert len(cases) == 1
    assert cases[0].deviation == DeviationType.BEHAVIORAL_DRIFT
