from __future__ import annotations

import tempfile
from pathlib import Path

from axor_eval.deprivation.engine import CANARY_PREFIX, FaultRecord, ToolDeprivationEngine
from axor_eval.replay.player import ReplayPlayer
from axor_eval.replay.recorder import ReplayRecorder


def _noop(*args, **kwargs):
    return {"results": [{"content": "real"}]}


def _make_engine() -> ToolDeprivationEngine:
    engine = ToolDeprivationEngine(seed="replay_test")
    engine.register("search", "silent_fail")
    engine.register("retrieve", "corrupt_retrieval")
    return engine


def test_recorder_writes_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()
        with ReplayRecorder(path, "search_timeout", engine) as rec:
            rec.record_action("search", "q='test'")
            engine.wrap("search", _noop)()
            rec.record_result("search", "error")
        assert path.exists()
        lines = path.read_text().splitlines()
        assert any('"type": "meta"' in l for l in lines)
        assert any('"type": "fault"' in l for l in lines)
        assert any('"type": "action"' in l for l in lines)
        assert any('"type": "close"' in l for l in lines)


def test_player_round_trip_fault_log():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()

        # Record
        with ReplayRecorder(path, "search_timeout", engine) as rec:
            rec.record_action("search", "q='test'")
            engine.wrap("search", _noop)()
            rec.record_action("retrieve", "q='test'")
            engine.wrap("retrieve", _noop)()

        original_faults = engine.fault_log

        # Replay
        player = ReplayPlayer(path)
        replayed_faults = player.fault_records()

        assert len(replayed_faults) == len(original_faults)
        for orig, replayed in zip(original_faults, replayed_faults):
            assert orig.tool_name == replayed.tool_name
            assert orig.mode == replayed.mode
            assert orig.canary == replayed.canary


def test_player_reconstruct_engine_matches_original():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()

        with ReplayRecorder(path, "s", engine) as rec:
            engine.wrap("search", _noop)()
            engine.wrap("retrieve", _noop)()

        player = ReplayPlayer(path)
        rebuilt = player.reconstruct_engine()

        # Rebuilt engine has same seed
        assert rebuilt._seed == engine._seed

        # Rebuilt engine produces same fault modes for same tools
        rebuilt.wrap("search", _noop)()
        rebuilt.wrap("retrieve", _noop)()

        orig_modes = {(r.tool_name, r.mode) for r in engine.fault_log}
        rebuilt_modes = {(r.tool_name, r.mode) for r in rebuilt.fault_log}
        assert orig_modes == rebuilt_modes


def test_player_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()
        with ReplayRecorder(path, "search_timeout", engine, env_config={"k": "v"}) as _:
            pass

        player = ReplayPlayer(path)
        manifest = player.manifest
        assert manifest.scenario_id == "search_timeout"
        assert manifest.seed == "replay_test"
        assert manifest.env_config == {"k": "v"}


def test_context_manager_closes():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()
        rec = ReplayRecorder(path, "s", engine)
        with rec:
            pass
        assert path.exists()
        assert rec._closed


def test_canary_survives_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.jsonl"
        engine = _make_engine()
        engine.wrap("retrieve", _noop)()  # drive corrupt_retrieval
        with ReplayRecorder(path, "s", engine):
            pass

        player = ReplayPlayer(path)
        faults = player.fault_records()
        corrupt = [f for f in faults if f.mode == "corrupt_retrieval"]
        assert len(corrupt) == 1
        assert corrupt[0].canary.startswith(CANARY_PREFIX)
