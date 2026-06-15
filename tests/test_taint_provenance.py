from __future__ import annotations

from axor_core.contracts.taint import TaintSource
from axor_core.taint.causal_root import CausalRoot
from axor_core.taint.engine import TaintEngine

# axor-core's taint model is per-value PROVENANCE: there is no session or
# cross-session taint *state* (TaintEngine docstring: "There is no session-taint
# state"). Provenance lives on values, is derived per value, and is inherited
# parent -> child via inherit_value_ledger. The old cross-session-scope /
# propagate / persist API this file used to exercise no longer exists in core;
# these tests pin eval to the model core actually implements.


def test_external_read_value_is_tainted() -> None:
    engine = TaintEngine(node_id="n")
    secret = "ExternalDocumentContentsAAAA"
    engine.register_value(secret, CausalRoot.external_read(TaintSource.WEB))
    assert engine.derive_value(secret).is_tainted


def test_constant_value_is_clean() -> None:
    engine = TaintEngine(node_id="n")
    # A value never registered as an external read carries no provenance.
    assert not engine.derive_value("PlainConstantWrittenByAgent").is_tainted


def test_sensitive_read_arms_confidentiality_floor() -> None:
    engine = TaintEngine(node_id="n")
    assert not engine.confidentiality_floor_active()
    engine.register_value(
        "ApiKeySkSupersecretValueCCCC",
        CausalRoot.external_read(TaintSource.MEMORY, sensitive=True),
    )
    # Floor arms on the FACT of the sensitive read (enforcement input).
    assert engine.confidentiality_floor_active()


def test_child_inherits_parent_value_taint() -> None:
    parent = TaintEngine(node_id="parent")
    payload = "PoisonedRetrievalChunkBBBB"
    parent.register_value(payload, CausalRoot.external_read(TaintSource.WEB))

    child = TaintEngine(node_id="child")
    assert not child.derive_value(payload).is_tainted   # before inheritance: clean
    child.inherit_value_ledger(parent)
    assert child.derive_value(payload).is_tainted        # after: carries parent taint


def test_independent_engine_does_not_see_other_taint() -> None:
    # The analog of the old "different node -> no taint": an engine that did NOT
    # inherit a ledger sees none of another engine's provenance, and is not
    # egress-restricted by another engine's sensitive read.
    tainted = TaintEngine(node_id="a")
    payload = "SecretFromEngineAOnlyDDDD"
    tainted.register_value(
        payload, CausalRoot.external_read(TaintSource.WEB, sensitive=True)
    )

    other = TaintEngine(node_id="b")
    assert not other.derive_value(payload).is_tainted
    assert not other.confidentiality_floor_active()
