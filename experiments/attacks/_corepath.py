"""Make the axor-core example payloads importable from the eval experiments.

These experiment harnesses live in axor-eval (the eval layer, which is *allowed*
to depend on axor-core — that is the one-way dependency direction) but reuse the
attack payloads and the AgentDojo driver that remain in the axor-core repo,
unchanged. We add the sibling axor-core checkout to ``sys.path`` so that
``examples.attacks.*``, ``run_agentdojo`` and ``agentdojo_adapter`` resolve, plus
this directory itself so the co-located harness modules import each other by name.

The core location defaults to a sibling checkout (``../axor-core`` relative to the
eval repo); override it with the ``AXOR_CORE_REPO`` environment variable when the
two repositories are not checked out side by side.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE = os.environ.get("AXOR_CORE_REPO") or os.path.abspath(
    os.path.join(_HERE, os.pardir, os.pardir, os.pardir, "axor-core"))

for _p in (
    _HERE,                                         # co-located harness modules (flat imports)
    _CORE,                                         # examples.attacks.*, examples.agentdojo.*
    os.path.join(_CORE, "examples", "agentdojo"),  # run_agentdojo, agentdojo_adapter
    os.path.join(_CORE, "examples", "attacks"),    # nnsi_experiment, split_doc_experiment
):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
