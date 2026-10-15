"""Ajar: which tasks are provisioned (gate passed) in modes a and b, per task, for one configuration
(AXOR_AJAR_CONFIG_DIR). SUITES limits the suites.   python provisioned_by_task.py OUT.json"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import paper_opl  # noqa: E402
import residuals  # noqa: E402
import run_ajar  # noqa: E402
from ajar.runner import run_defense  # noqa: E402

keep = set(os.environ.get("SUITES", "banking,slack,travel,workspace").split(","))
data = [(s, p) for s, p in run_ajar.load(None) if s.task.suite in keep]
out = {}
for mode, levels in (("a", None), ("b", "L1+L2s")):
    d = (axor_ajar.grants_defense(mode, levels, grant_args=residuals.r0(), confirm="oracle") if levels else
         axor_ajar.AxorDefense(mode, integrity_default="context", integrity_origins="request-only"))
    out[mode] = {}
    for spec, probes in data:
        if spec.is_gradeable:
            sc = paper_opl.score(mode, probes, run_defense(d, spec, probes))
            out[mode][str(spec.task)] = bool(sc.gate_passed)
    print(mode, sum(out[mode].values()), "/", len(out[mode]), flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
