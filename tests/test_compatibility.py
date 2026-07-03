"""Warn-only axor-core compatibility gate (same pattern as axor-sentinel's)."""
from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from axor_eval import compatibility
from axor_eval.compatibility import (
    MAX_AXOR_CORE,
    MIN_AXOR_CORE,
    _parse,
    check_axor_core_version,
    warn_once_on_skew,
)


def test_parse_handles_suffixes():
    assert _parse("0.8.0") == (0, 8, 0)
    assert _parse("0.8.1+local") == (0, 8, 1)
    assert _parse("0.9.0-rc1") == (0, 9, 0)
    assert _parse("1.0") == (1, 0, 0)


def test_installed_core_is_in_declared_range():
    # The sibling checkout this repo is validated against must pass the gate.
    assert check_axor_core_version() is True


def test_out_of_range_warns_not_raises():
    with patch("axor_core.__version__", "0.7.0"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert check_axor_core_version() is False
        assert any("outside the range" in str(w.message) for w in caught)


def test_out_of_range_raises_when_requested():
    with patch("axor_core.__version__", "99.0.0"):
        with pytest.raises(RuntimeError, match="outside the range"):
            check_axor_core_version(raise_on_mismatch=True)


def test_range_bounds_are_sane():
    assert MIN_AXOR_CORE < MAX_AXOR_CORE


def test_warn_once_is_idempotent():
    compatibility._checked = False
    warn_once_on_skew()
    assert compatibility._checked is True
    warn_once_on_skew()  # second call: no work, no raise
