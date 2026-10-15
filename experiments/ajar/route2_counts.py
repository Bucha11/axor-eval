"""Route 2: per source (L1 / L2) — admitted in total, and admitted with a value that names an existing
object of the initial state (user, channel, address, IBAN, id, ...); k over the second (as
route2_entities.py).   ROUTES_TAG=... ROUTES_CONFIG=... python route2_counts.py"""
import collections
import gzip
import json
import os
import statistics

import yaml

import route2_entities as r2

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    from agentdojo.task_suite.load_suites import get_suite
    tag = os.environ["ROUTES_TAG"]
    p = os.path.join(HERE, "results", f"residuals_routes_{tag}.json")
    d = json.load(gzip.open(p + ".gz") if os.path.exists(p + ".gz") else open(p))
    plan_has = {(s["task"], s["sink"]): s["plan_has_sink"] for s in d["route2_stats"] if "task" in s}
    ents = {s: r2.entities(s, get_suite("v1", s).load_and_inject_default_environment({}))
            for s in ("banking", "slack", "travel", "workspace")}
    cfg = {s: yaml.safe_load(open(os.path.join(os.environ["ROUTES_CONFIG"], f"{s}.yaml"))) for s in ents}
    out = {}
    for source in ("L1", "L2"):
        adm = [r for r in d["route2"] if r["res"]["b"][0] and r["res"]["b"][1] == source]
        exist = []
        for r in adm:
            k = r2.kind_of(r["suite"], r["arg"])
            v = r["call"][r["arg"]]
            if k is not None and all(r2.canon(x) in ents[r["suite"]][k] for x in (v if isinstance(v, list) else [v])):
                exist.append(r)
        pts = collections.defaultdict(set)
        for r in exist:
            pts[(r["suite"], r["task"], r["sink"], r["arg"])].add(json.dumps(r["call"][r["arg"]], default=str))
        ks = []
        for pt, vs in pts.items():
            if source == "L2":
                o = (cfg[pt[0]].get("operator_sets") or {}).get(pt[2], {}).get(pt[3])
                ks.append(len(o) if o else len(vs) + 1)
            else:
                ks.append(len(vs) + (1 if plan_has.get((pt[1], pt[2])) else 0))
        out[source] = {"admitted": len(adm), "admitted_existing": len(exist), "decision_points": len(ks),
                       "k": ks and [statistics.median(ks), r2.pct(ks, 0.9), max(ks)]}
    print(json.dumps(out))
    json.dump(out, open(os.path.join(HERE, "results", f"route2_counts_{tag}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
