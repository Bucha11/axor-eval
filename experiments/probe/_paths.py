"""Make axor_eval, axor_probe and axor_core importable for this scenario script.

This experiment imports axor_eval (the contract, EvidenceCase) and axor_probe (the
directional-residual operator under test), and transitively axor_core. axor_eval
is the top of the stack, so depending on axor_probe here — at the experiment-script
level, not in the shipped package — respects the dependency direction. The probe
and core checkouts default to siblings of the eval repo; override with
AXOR_PROBE_REPO / AXOR_CORE_REPO.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EVAL_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
_SIBLINGS = os.path.abspath(os.path.join(_EVAL_ROOT, os.pardir))

_PATHS = [
    _EVAL_ROOT,                                                    # axor_eval
    os.environ.get("AXOR_PROBE_REPO") or os.path.join(_SIBLINGS, "axor-probe"),
    os.environ.get("AXOR_CORE_REPO") or os.path.join(_SIBLINGS, "axor-core"),
]

for _p in _PATHS:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
