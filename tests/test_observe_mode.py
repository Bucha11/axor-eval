from __future__ import annotations

from unittest.mock import MagicMock

from axor_core.contracts.degradation import DegradationLevel
from axor_core.contracts.mode import ExecutionMode
from axor_core.contracts.policy import ExecutionPolicy
from axor_core.contracts.taint import TaintState
from axor_core.contracts.trace import DegradationTransitionEvent, TraceEventKind
from axor_core.degradation.engine import DegradationEngine


def _intent(tool: str = "bash", cross_origin: bool = False) -> MagicMock:
    intent = MagicMock()
    intent.tool = tool
    intent.destination_kind = "external_domain" if cross_origin else "local"
    intent.operation = "network_request" if cross_origin else "read"
    intent.executes_generated_code = False
    intent.after_external_read = True  # triggers instruction pressure
    intent.provenance = "web"
    return intent


def _denial() -> MagicMock:
    return MagicMock()


def test_observe_mode_importable():
    assert ExecutionMode.OBSERVE == "observe"


def test_observe_mode_does_not_escalate_level():
    engine = DegradationEngine(observe=True)
    intent = _intent("bash")
    taint = TaintState()

    for _ in range(10):
        engine.record_signal(intent, _denial(), taint)

    assert engine.state.level == DegradationLevel.NORMAL


def test_observe_mode_still_emits_transition_events():
    engine = DegradationEngine(observe=True)
    intent = _intent("bash")
    taint = TaintState()

    engine.record_signal(intent, _denial(), taint)
    events = engine.drain_events()

    transition_events = [
        e for e in events
        if e.kind == TraceEventKind.DEGRADATION_TRANSITION
    ]
    assert len(transition_events) > 0
    assert isinstance(transition_events[0], DegradationTransitionEvent)


def test_enforcement_mode_does_escalate():
    engine = DegradationEngine(observe=False)
    intent = _intent("bash")
    taint = TaintState()

    # Trigger tool pressure threshold (default 2)
    engine.record_signal(intent, _denial(), taint)
    engine.record_signal(intent, _denial(), taint)
    engine.record_signal(intent, _denial(), taint)

    assert engine.state.level > DegradationLevel.NORMAL


def test_observe_mode_transition_emitted_exactly_once():
    engine = DegradationEngine(observe=True)
    intent = _intent("bash")
    taint = TaintState()

    for _ in range(5):
        engine.record_signal(intent, _denial(), taint)

    events = engine.drain_events()
    transition_events = [e for e in events if e.kind == TraceEventKind.DEGRADATION_TRANSITION]
    # Shadow monotonicity: each distinct transition fires exactly once
    assert len(transition_events) == len({e.payload.get("new_level") or getattr(e, "new_level", None) for e in transition_events})


def test_from_mode_observe():
    engine = DegradationEngine.from_mode(ExecutionMode.OBSERVE)
    assert engine._observe is True
    assert engine.state.level == DegradationLevel.NORMAL


def test_from_mode_production():
    engine = DegradationEngine.from_mode(ExecutionMode.PRODUCTION)
    assert engine._observe is False


def test_observe_apply_to_policy_returns_base():
    engine = DegradationEngine(observe=True)
    intent = _intent("bash")
    taint = TaintState()

    for _ in range(10):
        engine.record_signal(intent, _denial(), taint)

    base = ExecutionPolicy()
    result = engine.apply_to_policy(base, source_id=None)
    assert result is base


def test_observe_cross_origin_stays_unblocked():
    engine = DegradationEngine(observe=True)
    intent = _intent("bash", cross_origin=True)
    taint = TaintState()

    engine.record_signal(intent, _denial(), taint)
    assert engine.state.level == DegradationLevel.NORMAL
