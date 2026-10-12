"""Pins the Progent check/use observations. Skipped unless PROGENT_REPO points at
a Progent clone and agentdojo / z3-solver / docstring_parser / jsonschema import
(see harness.py for the run line)."""
from __future__ import annotations

import os
import sys

import pytest

if not os.environ.get("PROGENT_REPO"):
    pytest.skip("PROGENT_REPO not set", allow_module_level=True)
pytest.importorskip("agentdojo")
pytest.importorskip("z3")

sys.path.insert(0, os.path.dirname(__file__))
import harness as h  # noqa: E402


@pytest.fixture(scope="module")
def results():
    T = h._progent()
    return {p.label: (p, h.run_probe(T, p)) for p in h.PROBES}


def test_legitimate_calls_pass_every_reading(results):
    for p, r in results.values():
        if p.legit:
            assert r["enforced"] and r["analysed"] and r["consumed"] == p.value


def test_every_attack_value_is_enforced_as_allowed_but_analysed_as_refused(results):
    for p, r in results.values():
        if not p.legit:
            assert r["enforced"], p.label
            assert not r["analysed"], p.label
            assert r["consumed"] == p.value, p.label  # the handler used it verbatim
