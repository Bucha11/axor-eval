"""Appendix D on the final configuration: the model-free bound (MODEL.md §8.11).

Banking user tasks 3, 4, 6, 15 through Ajar's gate, configuration A (L1, no human) and
B (L1+L4 oracle). The arm (with / without the operator sets O) is the config directory:

    AXOR_AJAR_CONFIG_DIR=<config_m1_content | copy without operator_sets> ARM=with|without \
    AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 AXOR_CORE_REPO=... python appendix_d.py

Writes results/appendix_d_<ARM>.json: per task and configuration, sufficiency, every denied
required call (tool, args, check, reason), and the attacker calls admitted (any sink).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_opl  # noqa: E402
import run_ajar  # noqa: E402

from ajar.core.types import Label, Verdict  # noqa: E402
from ajar.runner import run_defense  # noqa: E402

TASKS = ("user_task_3", "user_task_4", "user_task_6", "user_task_15")
SPEC = {"A": "grants:L1+L2s:R0", "B": "grants:L1+L2s+L4:R0"}


def main():
    arm = os.environ["ARM"]
    def tid(spec):
        return str(spec.task).split("/")[-1].split("@")[0]
    data = [(s, p) for s, p in run_ajar.load("banking") if tid(s) in TASKS]
    out = {"arm": arm, "config_dir": os.environ.get("AXOR_AJAR_CONFIG_DIR"), "tasks": {}}
    for c, spec_name in SPEC.items():
        d = paper_opl.make(spec_name)
        for spec, probes in data:
            t = tid(spec)
            n0 = len(d.log)
            res = run_defense(d, spec, probes)
            log = d.log[n0:]
            req = [(r, log[i]) for i, r in enumerate(res)
                   if r.probe.scored and r.probe.expected_label is Label.ALLOW and r.probe.required]
            denied, seen = [], set()
            for r, e in req:
                if r.verdict is Verdict.ALLOW:
                    continue
                k = (r.probe.candidate.tool, json.dumps(dict(r.probe.candidate.args), sort_keys=True, default=str))
                if k in seen:
                    continue
                seen.add(k)
                denied.append({"tool": k[0], "args": dict(r.probe.candidate.args), "check": e.get("category"),
                               "reason": (e.get("reason") or "")[:240], "prefix": len(r.probe.context.prefix)})
            atk, seen = [], set()
            for i, r in enumerate(res):
                if r.probe.scored and r.probe.fault_class.value == "ATTACKER_SEEDED" and r.verdict is Verdict.ALLOW:
                    k = (r.probe.candidate.tool, json.dumps(dict(r.probe.candidate.args), sort_keys=True, default=str))
                    if k not in seen:
                        seen.add(k)
                        atk.append({"tool": k[0], "args": dict(r.probe.candidate.args),
                                    "check": log[i].get("category"), "reason": (log[i].get("reason") or "")[:240]})
            out["tasks"].setdefault(t, {})[c] = {
                "required": len(req), "admitted": sum(r.verdict is Verdict.ALLOW for r, _ in req),
                "sufficient": all(r.verdict is Verdict.ALLOW for r, _ in req),
                "denied_required": denied, "attacker_calls_admitted": atk}
            v = out["tasks"][t][c]
            print(f"{arm:8s} {c} {t:28s} sufficient={v['sufficient']!s:5s} "
                  f"{v['admitted']}/{v['required']} denied={[(x['tool'], x['check']) for x in denied]} "
                  f"attacker_admitted={[(x['tool'], x['args'].get('recipient')) for x in atk]}", flush=True)
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                                     f"appendix_d_{arm}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
