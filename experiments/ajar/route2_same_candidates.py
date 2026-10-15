"""Route 2, same candidate set: re-decide (mode b) the candidates that c9v5 with 9.20 admits and c9v5
without it never generated, under the configuration in AXOR_AJAR_CONFIG_DIR."""
import gzip
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import residuals  # noqa: E402
import run_ajar  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load(t):
    p = os.path.join(HERE, "results", f"residuals_routes_{t}.json")
    return json.load(gzip.open(p + ".gz")) if os.path.exists(p + ".gz") else json.load(open(p))


a, b = load("r2_c9v5")["route2"], load("r2_c9v5u")["route2"]
key = lambda r: (r["task"], r["sink"], r["arg"], json.dumps(r["call"], sort_keys=True))
seen = {key(r) for r in a}
new = [r for r in b if key(r) not in seen]
specs = {str(s.task): s for s, _ in run_ajar.load(None)}
res = Counter()
diff = []
for r in new:
    d = residuals.run(specs[r["task"]], "b", r["k"], [(r["sink"], r["call"], None)])
    with920 = r["res"]["b"][0]
    res[(with920, bool(d.allowed))] += 1
    if with920 and not d.allowed:
        diff.append({"task": r["task"], "sink": r["sink"], "arg": r["arg"], "call": r["call"],
                     "source_with_9_20": r["res"]["b"][1], "without": d.category})
out = {"new_candidates": len(new), "(with 9.20, without) admitted": {str(k): v for k, v in res.items()},
       "admitted_only_with_9_20": len(diff), "rows": diff}
print(json.dumps({k: v for k, v in out.items() if k != "rows"}))
for x in diff[:40]:
    print(x["task"].split("/")[1], x["task"].split("/")[2][:14], x["sink"], x["arg"],
          json.dumps(x["call"].get(x["arg"]))[:90], x["source_with_9_20"], x["without"])
json.dump(out, open(os.path.join(HERE, "results", "route2_same_candidates_c9v5.json"), "w"), indent=1, default=str)
