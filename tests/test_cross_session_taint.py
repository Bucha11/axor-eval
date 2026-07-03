"""Taint continuity contracts eval relies on, against core 0.8's value ledger.

core 0.8 replaced the session-scoped ``TaintEngine.propagate()`` /
``cross_session_persist()`` API with a per-value ledger: values are registered
with a ``CausalRoot`` and sinks decide on ``derive_value()``. Cross-session
continuity is no longer a TaintEngine feature — it lives in axor-sentinel's
``ReputationSnapshot`` (sessions feed the sentinel audit cycle; the enricher
carries reputation back into the next session's intents). These tests pin the
pieces of that story eval's runner actually touches.
"""
from __future__ import annotations

from axor_core.contracts.taint import TaintScope, TaintSource
from axor_core.taint.causal_root import CausalRoot
from axor_core.taint.engine import TaintEngine


def test_cross_session_scope_exists():
    # The vocabulary survives in the contracts even though the engine no longer
    # takes a scope — sentinel/reporting layers still label cross-session flows.
    assert TaintScope.CROSS_SESSION == "cross_session"


def test_external_tool_value_is_tainted():
    # The runner's _govern wrapper registers every governed tool result with an
    # MCP external-read root; the derived causal root must carry the taint.
    engine = TaintEngine(node_id="n")
    result = {"documents": ["external payload"]}
    engine.register_value(result, CausalRoot.external_read(TaintSource.MCP))
    root = engine.derive_value(result)
    assert root.is_tainted
    assert TaintSource.MCP in root.sources


def test_constant_value_stays_clean():
    engine = TaintEngine(node_id="n")
    engine.register_value({"x": "external"}, CausalRoot.external_read(TaintSource.MCP))
    assert not engine.derive_value("a literal the agent typed").is_tainted


def test_session_shadow_reflects_external_registration():
    # Observe-only session-wide shadow: the density meter's coarse flag must
    # flip once any external value is registered.
    engine = TaintEngine(node_id="n")
    assert engine.session_shadow() == (False, False)
    engine.register_value("payload", CausalRoot.external_read(TaintSource.MCP))
    any_tainted, _ = engine.session_shadow()
    assert any_tainted


def test_child_engine_inherits_value_ledger():
    # In-core continuity across engines: a child session/node inherits the
    # parent's per-value provenance (the successor of parent_inherited taint).
    parent = TaintEngine(node_id="parent")
    payload = {"content": "fetched from the web"}
    parent.register_value(payload, CausalRoot.external_read(TaintSource.WEB))

    child = TaintEngine(node_id="child")
    assert not child.derive_value(payload).is_tainted
    child.inherit_value_ledger(parent)
    assert child.derive_value(payload).is_tainted
