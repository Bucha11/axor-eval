"""Skipped unless ADAPTERS points at clones of axor-claude, axor-openrouter and
axor-langchain and their dependencies import (see harness.py for the run line)."""
from __future__ import annotations

import os
import sys

import pytest

if not os.environ.get("ADAPTERS"):
    pytest.skip("ADAPTERS not set", allow_module_level=True)
pytest.importorskip("anthropic")
pytest.importorskip("langchain_core")

sys.path.insert(0, os.path.dirname(__file__))
import harness as h  # noqa: E402


def test_four_adapters_reach_one_decision():
    out = h.render()  # asserts identity across adapters internally
    assert out.count("deny (taint_enforcement)") == 4
    assert out.count("('GB29NWBK60161331926819', 500.0)") == 4
