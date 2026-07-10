"""axor-core compatibility check.

axor-eval imports deep into axor-core (GovernedSession, CapabilityExecutor,
TaintEngine, TraceCollector, BudgetTracker), so a core release that reshapes
any of those APIs breaks eval at runtime — as the 0.8 taint value-ledger
rework did. mypy is configured to ignore missing axor_core imports, so version
skew surfaces only when a scenario runs.

This module declares the compatible axor-core range (same pattern as
axor-sentinel's compatibility.py) and offers a warn-only check. EvalRunner
calls it once per process at construction; it never raises by default, so it
cannot take down a run — it makes skew visible instead of silent.
"""

from __future__ import annotations

import logging
import warnings

log = logging.getLogger("axor.eval.compat")

# Inclusive lower bound, exclusive upper bound — the axor-core range these
# eval integrations were validated against. Bump on contract-affecting releases.
MIN_AXOR_CORE = (0, 8, 0)
MAX_AXOR_CORE = (0, 10, 0)

_checked = False


def _parse(version: str) -> tuple[int, int, int]:
    parts = version.split("+")[0].split("-")[0].split(".")
    nums: list[int] = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])  # type: ignore[return-value]


def check_axor_core_version(*, raise_on_mismatch: bool = False) -> bool:
    """Return True if the installed axor-core is within the compatible range.

    Emits a warning (or raises, if requested) on skew or when axor-core has no
    readable version. Safe to call at startup; EvalRunner calls it once per
    process.
    """
    try:
        import axor_core
        installed = _parse(getattr(axor_core, "__version__", "0.0.0"))
    except Exception as exc:  # pragma: no cover - environment-specific
        msg = f"axor-core not importable for compatibility check: {exc}"
        if raise_on_mismatch:
            raise RuntimeError(msg) from exc
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return False

    if MIN_AXOR_CORE <= installed < MAX_AXOR_CORE:
        return True

    msg = (
        f"axor-core {'.'.join(map(str, installed))} is outside the range "
        f"axor-eval was validated against "
        f"[{'.'.join(map(str, MIN_AXOR_CORE))}, {'.'.join(map(str, MAX_AXOR_CORE))}). "
        "Contract drift may break scenario runs at runtime; pin compatible versions."
    )
    if raise_on_mismatch:
        raise RuntimeError(msg)
    warnings.warn(msg, RuntimeWarning, stacklevel=2)
    log.warning(msg)
    return False


def warn_once_on_skew() -> None:
    """Process-wide, warn-only convenience used by EvalRunner.__init__."""
    global _checked
    if _checked:
        return
    _checked = True
    check_axor_core_version(raise_on_mismatch=False)
