"""Revision 8, item 3: what O opens. For a defense configuration with and without O,
the admitted Ajar attacks and the landed replay attacks (1887), by injection task and tool.

    AXOR_CORE_REPO=... python rev8_breakdown.py ajar   <cfg_dir> <a|b|c-oracle|c-naive|c-view> <tag>
    AXOR_CORE_REPO=... python rev8_breakdown.py replay <cfg_dir> <a|b|c-oracle|c-naive|c-view> <tag>
(revision 9: AXOR_AJAR_L2=tuple makes L2 the kernel's tuple templates)
-> results/rev8_breakdown_<mode>_<tag>.json
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MODE, CFG, CONF, TAG = sys.argv[1:5]
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, CFG)

import axor_ajar  # noqa: E402
import residuals  # noqa: E402


def ajar():
    import run_ajar
    from ajar.runner import run_defense
    if CONF == "a":
        d = axor_ajar.AxorDefense(f"{CFG}|a", integrity_default="context", integrity_origins="request-only")
    elif CONF == "b":
        d = axor_ajar.grants_defense(f"{CFG}|b", "L1+L2s", grant_args=residuals.r0(), confirm="oracle")
    else:  # c-oracle | c-naive | c-view
        d = axor_ajar.grants_defense(f"{CFG}|{CONF}", "L1+L2s+L4", grant_args=residuals.r0(),
                                     confirm=CONF.split("-", 1)[1])
    rows = []
    for spec, probes in run_ajar.load(None):
        for r in run_defense(d, spec, probes):
            p = r.probe
            if p.fault_class.value != "ATTACKER_SEEDED":
                continue
            rows.append({"task": str(spec.task), "suite": spec.task.suite, "key": repr(p.candidate.key()),
                         "injection": p.ground_truth.get("injection_id") or p.probe_id.split("-k")[0],
                         "k": len(p.context.prefix),
                         "tool": p.candidate.tool, "args": dict(p.candidate.args),
                         "allowed": r.verdict.value == "ALLOW"})
    # an attack (task, injection) is admitted when every one of its sink probes is admitted at
    # its earliest decision point
    by = defaultdict(list)
    for x in rows:
        by[(x["task"], x["injection"])].append(x)
    admitted = []
    for (task, inj), xs in by.items():
        first = {}
        for x in sorted(xs, key=lambda x: x["k"]):
            first.setdefault(x["key"], x)  # the scorer's rule: earliest decision point per sink
        if all(x["allowed"] for x in first.values()):
            admitted.append({"task": task, "suite": xs[0]["suite"], "injection": inj,
                             "tools": sorted({x["tool"] for x in first.values()}),
                             "args": [x["args"] for x in first.values()]})
    return {"attacks": len(by), "admitted": admitted}


def replay():
    import replay_runs as RR
    from agentdojo.task_suite.load_suites import get_suite
    variant = {"a": ("ctx", None), "b": ("ctx", "L1+L2s", "R0")}.get(CONF) or \
        ("ctx", "L1+L2s+L4", "R0", CONF.split("-", 1)[1])
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
    landed = []
    n = 0
    orig_eval = None
    for model in ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"):
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = get_suite(RR.VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(path))
                admitted_calls = []
                real = RR.factory

                def factory(*a, **k):
                    mk = real(*a, **k)

                    def make():
                        g = mk()
                        ev = g.evaluate

                        def evaluate(tool, args):
                            d = ev(tool, args)
                            if d.allowed:
                                admitted_calls.append({"tool": tool, "args": dict(args),
                                                       "grant": getattr(d, "grant_source", None)})
                            return d
                        g.evaluate = evaluate
                        return g
                    return make
                RR.factory = factory
                try:
                    util, sec = RR.replay(variant, suite, run)
                finally:
                    RR.factory = real
                n += 1
                if sec:
                    landed.append({"model": model, "suite": sname, "user_task": run["user_task_id"],
                                   "injection": run.get("injection_task_id"), "admitted_calls": admitted_calls})
    return {"runs": n, "landed": landed}


if __name__ == "__main__":
    res = ajar() if MODE == "ajar" else replay()
    json.dump(res, open(os.path.join(HERE, "results", f"rev8_breakdown_{MODE}_{TAG}.json"), "w"), indent=1, default=str)
    items = res["admitted"] if MODE == "ajar" else res["landed"]
    print(MODE, TAG, len(items), "admitted/landed")
    print(Counter((x["suite"], x["injection"]) for x in items).most_common())
