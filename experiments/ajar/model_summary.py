"""Summary for MODEL.md §6: config_rule, P13, M0, M1, M1+content — Ajar (provisioned,
sufficiency and OPL with 95% CI, attacks), replay 1887 (ASR per mode), admitted attacks by
injection task and tool, and the 288 benign trajectories without a human (tasks with no refusal).

    python model_summary.py [tag ...]   -> results/model_summary.json + printed tables
"""
import gzip
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
CFG = {"config_rule": "rule7base", "P13": "rule13", "M0": "model", "M1": "m1", "M1+content": "m1c", "M1+content, target args": "m1d", "final (8.7)": "m1e", "FINAL": "final"}
BD = {"config_rule": "rule", "P13": "rule13", "M0": "model", "M1": "m1", "M1+content": "m1c", "M1+content, target args": "m1d", "final (8.7)": "m1e", "FINAL": "final"}
MODES = [("a", "no grants"), ("b", "grants, no human"), ("c-oracle", "perfect human"),
         ("c-view", "attentive human"), ("c-naive", "careless human")]
REPLAY = {"a": "axor-ctx-request-only", "b": "R0 L1+L2s", "c-oracle": "R0 L1+L2s+L4 oracle",
          "c-view": "R0 L1+L2s+L4 view", "c-naive": "R0 L1+L2s+L4 naive"}
SUITES = ("banking", "slack", "travel", "workspace")


def jl(p):
    if os.path.exists(p):
        return json.load(open(p))
    if os.path.exists(p + ".gz"):
        return json.load(gzip.open(p + ".gz"))
    return None


def main(names):
    out = {}
    for n in names:
        t, b = CFG[n], BD[n]
        aj = jl(os.path.join(R, f"residuals_ajar_attacks_{t}_paper.json")) or {}
        rp = (jl(os.path.join(R, f"residuals_replay_{t}_paper.json")) or {}).get("rows", {})
        row = {}
        for m, _ in MODES:
            v = aj.get(m)
            r = rp.get(REPLAY[m], {}).get("all")
            bd = {}
            for kind in ("ajar", "replay"):
                d = jl(os.path.join(R, f"rev8_breakdown_{kind}_{b}_{m}.json"))
                if d:
                    items = d["admitted"] if kind == "ajar" else d["landed"]
                    if kind == "ajar":
                        c = Counter((x["suite"], x["injection"], ",".join(x["tools"])) for x in items)
                    else:
                        c = Counter((x["suite"], x["injection"]) for x in items)
                    bd[kind] = {" / ".join(k): v_ for k, v_ in c.most_common()}
            row[m] = {
                "provisioned": v and v["provisioned"], "attacks": v and v["attacks"],
                "sufficiency": v and [v["sufficiency"], v["ci95"]["sufficiency"]],
                "opl": v and [v["opl"]["earliest"], v["ci95"]["opl"]],
                "replay_asr": r and f"{r['attacks_landed']}/{r['runs']}",
                "replay_utility": r and r["utility"], "breakdown": bd}
        benign = {}
        rows = jl(os.path.join(R, "replay_live", f"rl_benign_{t}_b.json"))
        if rows:
            per = {s: [0, 0] for s in SUITES}
            for x in rows:
                per[x["suite"]][1] += 1
                per[x["suite"]][0] += all(c["allowed"] for c in x["calls"])
            benign = {s: f"{a}/{b_}" for s, (a, b_) in per.items()}
            benign["all"] = f"{sum(a for a, _ in per.values())}/{sum(b_ for _, b_ in per.values())}"
        out[n] = {"modes": row, "benign_no_refusal_no_human": benign}
    json.dump(out, open(os.path.join(R, "model_summary.json"), "w"), indent=1)
    for m, label in MODES:
        print(f"\n## {label}")
        for n in names:
            x = out[n]["modes"][m]
            if not x["provisioned"]:
                continue
            print(f"  {n:11} tasks {x['provisioned']:>6} suff {x['sufficiency'][0]:.3f} {x['sufficiency'][1]} "
                  f"OPL {x['opl'][0]:.3f} {x['opl'][1]} attacks {x['attacks']:>7} replay ASR {x['replay_asr']} util {x['replay_utility']}")
            for kind, c in x["breakdown"].items():
                print(f"      {kind:6} {c}")
    print("\n## benign 288 without a human: trajectories with no refusal")
    for n in names:
        print(f"  {n:11} {out[n]['benign_no_refusal_no_human']}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(CFG))
