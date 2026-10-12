"""Pins the cells of the Axor/ROPE comparison that the write-up relies on.

Skipped unless ROPE_REPO points at a ROPE checkout and PyYAML/jsonschema are
importable (ROPE's own dependencies); see README.md. Every assertion is one
claim in axor-core docs/rope-comparison.md, so a change in either system that
moves a cell fails here first.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("yaml")
pytest.importorskip("jsonschema")
if not os.environ.get("ROPE_REPO"):
    pytest.skip("ROPE_REPO not set", allow_module_level=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

COMMIT = h.setup()


@pytest.fixture(scope="module")
def cells():
    return {(c.row, c.label): cs for c, cs in h.matrix()}


def _violated(cell) -> bool:
    return cell.executed and any(h.NOT_STATED not in e for e in cell.effects)


def test_pinned_rope_commit():
    assert COMMIT.startswith(h.ROPE_COMMIT)


def test_the_users_call_executes_everywhere(cells):
    for cell in cells[("legit", "the user's payment")].values():
        assert cell.executed and not cell.effects


def test_row3_composites_pass_rope_and_reach_a_splitting_consumer(cells):
    for label in ("composite 'A,X' — splitting consumer", "composite 'A X' — splitting consumer"):
        row = cells[("3", label)]
        assert _violated(row["ROPE"]) and _violated(row["ROPE+bound"])
        assert not any(row[n].executed for n in ("Axor-origin", "Axor+bound/att", "Axor+bound/ctr"))


def test_row4_only_the_contract_closes_presence_and_alias(cells):
    for label in ("absent amount (handler sweeps)", "alias field iban=X"):
        row = cells[("4", label)]
        assert _violated(row["ROPE+bound"]) and _violated(row["Axor+bound/att"])
        assert not row["Axor+bound/ctr"].executed
    # without a contract Axor has the same alias gap as ROPE — the difference is the contract
    assert _violated(cells[("4", "alias field iban=X")]["Axor-origin"])


def test_row6_rope_admits_an_unlisted_tool_axor_refuses_it(cells):
    row = cells[("6", "state-changing tool missing from the table")]
    assert _violated(row["ROPE"]) and not row["Axor-origin"].executed


def test_row8_is_scope_not_a_rope_violation(cells):
    row = cells[("8", "secret read, then pay the trusted recipient with it")]
    assert row["ROPE"].executed and not _violated(row["ROPE"])
    assert not row["Axor-origin"].executed


def test_row9_is_policy_content(cells):
    row = cells[("9", "amount 5000 to the trusted recipient")]
    assert not row["ROPE+bound"].executed and not row["Axor+bound/att"].executed


def test_contract_turns_a_string_amount_from_utility_loss_into_execution(cells):
    row = cells[("legit", "the user's payment, amount as a string")]
    assert not row["ROPE+bound"].executed and not row["Axor+bound/att"].executed
    assert row["Axor+bound/ctr"].executed


def test_row2_axor_launders_through_a_benign_declared_writer():
    results = {label: cell for label, _, cell in h.record_closure()}
    assert not results["ROPE — list_payees not a record tool (as shipped)"].executed
    assert not results["Axor — add_payee declared integrity sink"].executed
    assert _violated(results["Axor — add_payee declared benign"])


def test_row2_strict_checks_record_closure_at_construction():
    """Under STRICT an explicit any-trusted with an open record is refused before
    any call runs; the closed declaration is accepted."""
    out = dict(h.strict_record_closure())
    assert out["Axor STRICT, any-trusted — add_payee declared integrity sink"] == "constructed"
    assert out["Axor STRICT, any-trusted — add_payee declared benign"].startswith(
        "refused at construction: strict record closure")
