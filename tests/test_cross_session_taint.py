from __future__ import annotations

import tempfile
from pathlib import Path

from axor_core.contracts.taint import TaintScope, TaintSource
from axor_core.taint.engine import TaintEngine


def test_cross_session_scope_exists():
    assert TaintScope.CROSS_SESSION == "cross_session"


def test_cross_session_is_widest():
    engine = TaintEngine(node_id="n")
    result = engine._wider_scope(TaintScope.SESSION, TaintScope.CROSS_SESSION)
    assert result == TaintScope.CROSS_SESSION


def test_cross_session_wider_than_all():
    engine = TaintEngine(node_id="n")
    for scope in [TaintScope.INTENT, TaintScope.NODE, TaintScope.SUBTREE, TaintScope.SESSION]:
        assert engine._wider_scope(scope, TaintScope.CROSS_SESSION) == TaintScope.CROSS_SESSION


def test_propagate_cross_session():
    engine = TaintEngine(node_id="n")
    state = engine.propagate(TaintSource.MEMORY, TaintScope.CROSS_SESSION)
    assert state.is_tainted
    assert state.scope == TaintScope.CROSS_SESSION


def test_cross_session_persist_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        snap_dir = Path(tmp) / "snapshots"

        # Session 1: taint and persist
        engine1 = TaintEngine(node_id="node_abc")
        engine1.propagate(TaintSource.WEB, TaintScope.SESSION)
        engine1.cross_session_persist(snap_dir)

        # Session 2: load — should detect taint
        engine2 = TaintEngine(node_id="node_abc")
        assert not engine2.state.is_tainted
        state = engine2.load_cross_session(snap_dir)
        assert state.is_tainted
        assert state.scope == TaintScope.CROSS_SESSION


def test_cross_session_load_different_node_no_taint():
    with tempfile.TemporaryDirectory() as tmp:
        snap_dir = Path(tmp) / "snapshots"

        engine1 = TaintEngine(node_id="node_abc")
        engine1.propagate(TaintSource.WEB, TaintScope.SESSION)
        engine1.cross_session_persist(snap_dir)

        engine2 = TaintEngine(node_id="node_xyz")
        state = engine2.load_cross_session(snap_dir)
        assert not state.is_tainted


def test_cross_session_load_no_snapshot_returns_clean():
    with tempfile.TemporaryDirectory() as tmp:
        snap_dir = Path(tmp) / "empty_snapshots"
        engine = TaintEngine(node_id="n")
        state = engine.load_cross_session(snap_dir)
        assert not state.is_tainted
