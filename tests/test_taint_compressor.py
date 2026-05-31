from __future__ import annotations

from axor_core.context.compressor import ContextCompressor
from axor_core.contracts.context import ContextFragment
from axor_core.contracts.policy import CompressionMode


def _fragment(
    content: str,
    kind: str = "tool_result",
    token_estimate: int = 100,
    taint_mark: str | None = None,
    value: str = "working",
    turn: int = 1,
) -> ContextFragment:
    return ContextFragment(
        kind=kind,
        content=content,
        token_estimate=token_estimate,
        source="test",
        taint_mark=taint_mark,
        value=value,
        turn=turn,
    )


def test_taint_mark_field_on_fragment():
    f = _fragment("data", taint_mark="AXOR_CANARY_abc")
    assert f.taint_mark == "AXOR_CANARY_abc"


def test_taint_mark_default_none():
    f = _fragment("data")
    assert f.taint_mark is None


def test_taint_survives_truncation():
    compressor = ContextCompressor()
    big_content = "x " * 2000  # > 2000 token estimate
    fragment = _fragment(
        content=big_content,
        kind="tool_result",
        token_estimate=3000,
        taint_mark="AXOR_CANARY_deadbeef",
        value="working",
    )
    result = compressor.compress([fragment], mode=CompressionMode.AGGRESSIVE, current_turn=1)

    tainted = [f for f in result.fragments if f.taint_mark == "AXOR_CANARY_deadbeef"]
    assert len(tainted) == 1, "taint_mark must survive tool_result truncation"


def test_taint_survives_prose_cap():
    compressor = ContextCompressor()
    big_prose = "I decided to do something. " * 500
    fragment = _fragment(
        content=big_prose,
        kind="assistant_prose",
        token_estimate=3000,
        taint_mark="AXOR_CANARY_prose123",
        value="working",
    )
    result = compressor.compress([fragment], mode=CompressionMode.AGGRESSIVE, current_turn=1)

    tainted = [f for f in result.fragments if f.taint_mark == "AXOR_CANARY_prose123"]
    assert len(tainted) == 1, "taint_mark must survive prose cap"


def test_taint_survives_path_normalization():
    compressor = ContextCompressor()
    fragment = _fragment(
        content="output",
        kind="fact",
        token_estimate=10,
        taint_mark="AXOR_CANARY_norm",
        value="working",
    )
    fragment = ContextFragment(
        kind=fragment.kind,
        content=fragment.content,
        token_estimate=fragment.token_estimate,
        source="/home/user/project/file.py",
        taint_mark=fragment.taint_mark,
        value=fragment.value,
        turn=fragment.turn,
    )
    result = compressor.compress([fragment], mode=CompressionMode.BALANCED, current_turn=1)

    tainted = [f for f in result.fragments if f.taint_mark == "AXOR_CANARY_norm"]
    assert len(tainted) == 1, "taint_mark must survive path normalization"


def test_untainted_fragment_stays_none():
    compressor = ContextCompressor()
    fragment = _fragment("x " * 2000, kind="tool_result", token_estimate=3000)
    result = compressor.compress([fragment], mode=CompressionMode.AGGRESSIVE, current_turn=1)
    assert all(f.taint_mark is None for f in result.fragments)
