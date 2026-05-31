from __future__ import annotations

import pytest

from axor_eval.deprivation.engine import (
    CANARY_PREFIX,
    DeprivationConfigError,
    FaultRecord,
    ToolDeprivationEngine,
    _derive_canary,
)


def _noop(*args, **kwargs):
    return {"results": [{"content": "real data"}]}


def test_silent_fail_returns_error_structure():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("search", "silent_fail")
    wrapped = engine.wrap("search", _noop)

    result = wrapped()
    assert result["error"] == "tool_unavailable"
    assert result["tool"] == "search"


def test_silent_fail_records_fault_log():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("search", "silent_fail")
    wrapped = engine.wrap("search", _noop)

    wrapped()

    assert len(engine.fault_log) == 1
    record = engine.fault_log[0]
    assert isinstance(record, FaultRecord)
    assert record.tool_name == "search"
    assert record.mode == "silent_fail"
    assert record.canary == ""


def test_corrupt_retrieval_injects_canary():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    wrapped = engine.wrap("retrieve", _noop)

    result = wrapped()

    docs = result.get("results", [])
    assert any(CANARY_PREFIX in str(d.get("content", "")) for d in docs)


def test_corrupt_retrieval_records_fault_log():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    wrapped = engine.wrap("retrieve", _noop)

    wrapped()

    record = engine.fault_log[0]
    assert record.mode == "corrupt_retrieval"
    assert CANARY_PREFIX in record.canary
    assert record.seed != ""


def test_canary_is_deterministic():
    c1 = _derive_canary("seed123")
    c2 = _derive_canary("seed123")
    assert c1 == c2
    assert c1.startswith(CANARY_PREFIX)


def test_canary_differs_per_seed():
    assert _derive_canary("a") != _derive_canary("b")


def test_wrap_all():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("search", "silent_fail")
    tools = {"search": _noop, "read": _noop}
    wrapped = engine.wrap_all(tools)

    assert wrapped["search"]() != wrapped["read"]()
    search_result = wrapped["search"]()
    assert "error" in search_result
    read_result = wrapped["read"]()
    assert "results" in read_result


def test_unregistered_tool_passes_through():
    engine = ToolDeprivationEngine(seed="test")
    wrapped = engine.wrap("unregistered", _noop)
    assert wrapped() == _noop()


def test_invalid_mode_raises():
    engine = ToolDeprivationEngine(seed="test")
    with pytest.raises(DeprivationConfigError, match="unknown deprivation mode"):
        engine.register("tool", "nonsense_mode")


def test_fault_log_immutable_copy():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("search", "silent_fail")
    engine.wrap("search", _noop)()

    log_copy = engine.fault_log
    log_copy.clear()
    assert len(engine.fault_log) == 1


def test_instruction_injection_injects_canary_command():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("tool", "instruction_injection")
    wrapped = engine.wrap("tool", _noop)

    result = wrapped()
    content = result.get("content", "")
    assert "EXECUTE_" in content
    record = engine.fault_log[0]
    assert record.canary.startswith("EXECUTE_")
    assert record.mode == "instruction_injection"


def test_corrupt_retrieval_canary_is_first():
    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    wrapped = engine.wrap("retrieve", _noop)

    result = wrapped()
    docs = result.get("results", [])
    assert CANARY_PREFIX in docs[0].get("content", ""), "canary must be prepended, not appended"


def test_corrupt_retrieval_list_return_preserves_original():
    def _list_fn(*args, **kwargs):
        return [{"content": "real"}]

    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    wrapped = engine.wrap("retrieve", _list_fn)

    result = wrapped()
    docs = result.get("results", [])
    assert len(docs) == 2
    assert CANARY_PREFIX in docs[0]["content"]
    assert docs[1]["content"] == "real"


def test_corrupt_retrieval_logs_before_fn_called():
    called = []

    def _raising(*args, **kwargs):
        called.append(True)
        raise RuntimeError("tool failed")

    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    wrapped = engine.wrap("retrieve", _raising)

    with pytest.raises(RuntimeError):
        wrapped()

    assert len(engine.fault_log) == 1
    assert engine.fault_log[0].mode == "corrupt_retrieval"


def test_corrupt_retrieval_calls_real_fn():
    called = []

    def _real(*args, **kwargs):
        called.append(True)
        return {"results": [{"content": "real"}]}

    engine = ToolDeprivationEngine(seed="test")
    engine.register("retrieve", "corrupt_retrieval")
    engine.wrap("retrieve", _real)()

    assert called, "corrupt_retrieval must call the real tool"


def test_instruction_injection_calls_real_fn():
    called = []

    def _real(*args, **kwargs):
        called.append(True)
        return {"content": "real output"}

    engine = ToolDeprivationEngine(seed="test")
    engine.register("tool", "instruction_injection")
    engine.wrap("tool", _real)()

    assert called, "instruction_injection must call the real tool"
