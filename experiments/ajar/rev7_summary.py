"""Revision 7 summary: config_rule vs config_rule + O, side by side.

    python rev7_summary.py   -> results/residuals_table_rule7.json + printed tables
"""
import gzip
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
TAGS = {"rule": "rule7base", "rule+O": "rule7o"}
SUITES = ("banking", "slack", "travel", "workspace")


def jload(p):
    if os.path.exists(p):
        return json.load(open(p))
    return json.load(gzip.open(p + ".gz"))


def ajar():
    out = {}
    for name, t in TAGS.items():
        d = jload(os.path.join(R, f"residuals_ajar_attacks_{t}_paper.json"))
        out[name] = {c: {"opl": v["opl"]["earliest"], "opl_ci95": v["ci95"]["opl"],
                         "sufficiency": v["sufficiency"], "suff_ci95": v["ci95"]["sufficiency"],
                         "provisioned": v["provisioned"], "attacks": v["attacks"]} for c, v in d.items()}
    return out


def replay1887():
    out = {}
    for name, t in TAGS.items():
        d = jload(os.path.join(R, f"residuals_replay_{t}_paper.json"))["rows"]
        out[name] = {v: {s: f"{r[s]['attacks_landed']}/{r[s]['runs']} util {r[s]['utility']} err {r[s]['errors']}"
                         for s in (*SUITES, "all")} for v, r in d.items()}
    return out


def routes():
    out = {}
    for name, t in TAGS.items():
        s = jload(os.path.join(R, f"residuals_routes_{t}.json"))["summary"]
        out[name] = {
            **{f"R1 {k.split('|')[1]}": v["all"] for k, v in s.items() if k.startswith("route1|")},
            "R2 redirect": {k: v for k, v in s["route2"].items()
                            if k in ("candidates", "a", "b", "c-oracle", "c-naive", "c-view")},
            "R3 rich": s["route3"],
        }
    return out


def denials(path):
    rows = jload(path)
    calls, tasks, ntasks = defaultdict(int), defaultdict(set), defaultdict(set)
    by_tool = defaultdict(int)
    for r in rows:
        key = (r.get("pass"), r["task"])
        ntasks[r["suite"]].add(key)
        for c in r["calls"]:
            if not c["allowed"]:
                calls[r["suite"]] += 1
                tasks[r["suite"]].add(key)
                by_tool[(r["suite"], c["tool"])] += 1
    return ({s: {"denied_calls": calls[s], "tasks_with_denial": len(tasks[s]), "tasks": len(ntasks[s])}
             for s in SUITES}, dict(sorted(by_tool.items())))


def live():
    out = {}
    for kind in ("v4", "v5", "benign_a", "benign_b"):
        for name, t in TAGS.items():
            fn = f"rl_{kind}_{t}.json" if kind in ("v4", "v5") else f"rl_benign_{t}_{kind[-1]}.json"
            per, tools = denials(os.path.join(R, "replay_live", fn))
            out.setdefault(kind, {})[name] = {"per_suite": per, "by_tool": {f"{s}/{x}": n for (s, x), n in tools.items()}}
    return out


if __name__ == "__main__":
    res = {"ajar": ajar(), "replay1887": replay1887(), "routes": routes(), "live": live()}
    json.dump(res, open(os.path.join(R, "residuals_table_rule7.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "live"}, indent=1))
    for kind, v in res["live"].items():
        print(f"\n## {kind}")
        for s in SUITES:
            print(f"  {s:9} " + "   ".join(f"{n}: {v[n]['per_suite'][s]['denied_calls']} calls / "
                                           f"{v[n]['per_suite'][s]['tasks_with_denial']} of {v[n]['per_suite'][s]['tasks']} tasks"
                                           for n in TAGS))
