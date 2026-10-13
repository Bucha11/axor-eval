"""Route 5: confirmations per task in the live o4-mini logs (grants + L4 oracle, 3 passes).

    python residuals_l4load.py   -> results/residuals_l4load.json

Per suite and pooled: mean, p95, p99, max of confirmations per (task, pass);
slack/user_task_4 excluded (as in live_paired.py). Cost of a budget = p99 (pooled):
the (task, pass) runs whose confirmations exceed it would have hit the budget.
"""
from __future__ import annotations

import ast
import glob
import json
import math
import os
import re
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results", "live_grants")
CONF = re.compile(r"confirmations:\s+\d+ over \d+ tasks \((\{.*\})\)")
SUITES = ("banking", "slack", "travel", "workspace")
N = {"banking": 16, "slack": 20, "travel": 20, "workspace": 40}
EXCLUDE = {("slack", "user_task_4")}


def q(xs, p):
    """Nearest-rank percentile."""
    xs = sorted(xs)
    return xs[max(0, math.ceil(p * len(xs)) - 1)]


def per_task():
    out = {s: [] for s in SUITES}
    for d in ("pass1", "pass2", "pass3"):
        for s in SUITES:
            seen = {}
            for path in glob.glob(os.path.join(R, d, f"{s}_*.log")):
                m = CONF.search(open(path).read())
                if m:
                    seen.update(ast.literal_eval(m.group(1)))
            # a task with no entry asked nothing
            tasks = [f"user_task_{i}" for i in range(N[s] + (1 if s == "slack" else 0))]
            for t in tasks:
                if (s, t) in EXCLUDE:
                    continue
                out[s].append((d, t, int(seen.get(t, 0))))
    return out


def stats(xs):
    return {"n": len(xs), "mean": round(statistics.mean(xs), 3), "p95": q(xs, 0.95), "p99": q(xs, 0.99),
            "max": max(xs), "zero_share": round(sum(1 for x in xs if x == 0) / len(xs), 3)}


def main():
    data = per_task()
    res = {s: stats([c for _, _, c in data[s]]) for s in SUITES}
    pooled = [c for s in SUITES for _, _, c in data[s]]
    res["all"] = stats(pooled)
    budget = res["all"]["p99"]
    over = [(s, d, t, c) for s in SUITES for d, t, c in data[s] if c > budget]
    res["budget_p99"] = {"budget": budget, "runs_over": len(over), "runs": len(pooled),
                         "share_over": round(len(over) / len(pooled), 4),
                         "over": [{"suite": s, "pass": d, "task": t, "confirmations": c} for s, d, t, c in over]}
    json.dump(res, open(os.path.join(HERE, "results", "residuals_l4load.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
