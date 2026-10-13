"""Paired cost of grants + L4 on o4-mini: pass i governed minus pass i undefended.

    python live_paired.py

Undefended pass 1 is the earlier same-day pass (results/live_o4mini/benign_*_undefended_*),
passes 2-3 are results/live_grants/undef{2,3}/; governed passes are
results/live_grants/pass{1,2,3}/. SD is the population SD over passes (divide by n),
as in the paper's cost table. The unpaired cost against the paper's 7-pass
baselines is shown next to it.
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
SUITES = ("banking", "slack", "travel", "workspace")
N = {"banking": 16, "slack": 21, "travel": 20, "workspace": 40}
if os.environ.get("EXCLUDE", "1") == "1":
    N["slack"] = 20
PAPER = {"banking": 67.9, "slack": 84.8, "travel": 62.5, "workspace": 84.3}
LINE = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+)\s+\(benign\)\s+utility=([Yn])")
# A task whose run raised (e.g. AgentDojo's own KeyError on slack user_task_4 when
# the agent posts to a page the environment does not have) counts as a failure, so
# every pass has the full denominator.
ERR = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+): ERROR")
CONF = re.compile(r"confirmations:\s+\d+ over \d+ tasks \((\{.*\})\)")
# slack/user_task_4 raises inside AgentDojo (KeyError on a page the environment
# lacks) in two undefended passes and reaches the check elsewhere: a harness
# failure, not the model's, so it is excluded from every condition (EXCLUDE=1).
EXCLUDE = {("slack", "user_task_4")} if os.environ.get("EXCLUDE", "1") == "1" else set()


def count(paths: list[str], suite: str = "") -> tuple[int, int]:
    ok = n = 0
    for p in paths:
        text = open(p).read()
        for m in LINE.finditer(text):
            if (suite, m.group(2)) in EXCLUDE:
                continue
            n += 1
            ok += m.group(3) == "Y"
        n += sum(1 for m in ERR.finditer(text) if (suite, m.group(2)) not in EXCLUDE)
    return ok, n


def confirmations(paths: list[str], suite: str) -> int:
    import ast
    c = 0
    for p in paths:
        m = CONF.search(open(p).read())
        if m:
            c += sum(v for k, v in ast.literal_eval(m.group(1)).items() if (suite, k) not in EXCLUDE)
    return c


# GOV_ROOT: the governed passes (pass1..3 under it); default the paper's live_grants run.
GOV_ROOT = os.environ.get("GOV_ROOT") or os.path.join(R, "live_grants")
DEN = re.compile(r"benign denials:\s+\d+\s+\((\[.*\])\)")


def passes() -> tuple[list[dict], list[dict]]:
    und = [{s: count(glob.glob(os.path.join(R, "live_o4mini", f"benign_{s}_undefended_*.log")), s) for s in SUITES}]
    for d in ("undef2", "undef3"):
        und.append({s: count(glob.glob(os.path.join(R, "live_grants", d, f"{s}_*.log")), s) for s in SUITES})
    gov = [{s: count(glob.glob(os.path.join(GOV_ROOT, d, f"{s}_*.log")), s) for s in SUITES}
           for d in ("pass1", "pass2", "pass3")]
    return und, gov


def pct(c):
    return 100 * c[0] / c[1] if c[1] else float("nan")


def main() -> dict:
    und, gov = passes()
    out = {"undefended": und, "governed": gov, "rows": {}}
    conf = {s: statistics.mean(confirmations(glob.glob(os.path.join(GOV_ROOT, d, f"{s}_*.log")), s) / N[s]
                               for d in ("pass1", "pass2", "pass3")) for s in SUITES}
    conf_all = statistics.mean(sum(confirmations(glob.glob(os.path.join(GOV_ROOT, d, f"{s}_*.log")), s)
                                   for s in SUITES) / sum(N.values()) for d in ("pass1", "pass2", "pass3"))
    hdr = (f"{'suite':10s} {'undefended (3)':>18s} {os.environ.get('LABEL', 'grants+L4') + ' (3)':>18s} {'paired cost':>15s} "
           f"{'vs paper':>10s} {'conf/task':>10s}")
    print(hdr)
    rows = list(SUITES) + ["all"]
    for s in rows:
        if s == "all":
            u = [100 * sum(p[x][0] for x in SUITES) / sum(p[x][1] for x in SUITES) for p in und]
            g = [100 * sum(p[x][0] for x in SUITES) / sum(p[x][1] for x in SUITES) for p in gov]
            paper = sum(PAPER[x] * N[x] for x in SUITES) / sum(N.values())
            complete = all(sum(p[x][1] for x in SUITES) == sum(N.values()) for p in und + gov)
        else:
            u = [pct(p[s]) for p in und]
            g = [pct(p[s]) for p in gov]
            paper = PAPER[s]
            complete = all(p[s][1] == N[s] for p in und + gov)
        d = [gi - ui for gi, ui in zip(g, u)]
        row = {"undefended": u, "governed": g, "paired": d,
               "undefended_mean": statistics.mean(u), "undefended_sd": statistics.pstdev(u),
               "governed_mean": statistics.mean(g), "governed_sd": statistics.pstdev(g),
               "paired_mean": statistics.mean(d), "paired_sd": statistics.pstdev(d),
               "unpaired_vs_paper": statistics.mean(g) - paper, "paper_undefended": paper,
               "complete": complete, "confirmations_per_task": conf_all if s == "all" else conf[s]}
        out["rows"][s] = row
        print(f"{s:10s} {row['undefended_mean']:>9.1f}% ± {row['undefended_sd']:4.1f} "
              f"{row['governed_mean']:>9.1f}% ± {row['governed_sd']:4.1f} "
              f"{row['paired_mean']:>+8.1f} ± {row['paired_sd']:4.1f} {row['unpaired_vs_paper']:>+9.1f} "
              f"{row['confirmations_per_task']:>9.2f}"
              f"{'' if complete else '  (incomplete)'}")
    out["n_tasks"] = sum(N.values())
    # per-(task, pass) confirmations: p95 / p99 / max per suite and pooled; remaining denials by tool
    import ast
    import math
    from collections import Counter
    per = {s: [] for s in SUITES}
    den = Counter()
    for d in ("pass1", "pass2", "pass3"):
        for s in SUITES:
            seen = {}
            for path in glob.glob(os.path.join(GOV_ROOT, d, f"{s}_*.log")):
                text = open(path).read()
                m = CONF.search(text)
                if m:
                    seen.update(ast.literal_eval(m.group(1)))
                dm = DEN.search(text)
                if dm:
                    den.update(x.split(":")[0] for x in ast.literal_eval(dm.group(1)))
            for i in range(N[s] + (1 if s == "slack" and EXCLUDE else 0)):
                t = f"user_task_{i}"
                if (s, t) not in EXCLUDE:
                    per[s].append(int(seen.get(t, 0)))

    def q(xs, p):
        xs = sorted(xs)
        return xs[max(0, math.ceil(p * len(xs)) - 1)]
    out["confirmations_dist"] = {s: {"mean": round(statistics.mean(v), 3), "p95": q(v, .95), "p99": q(v, .99),
                                     "max": max(v)} for s, v in list(per.items()) + [("all", sum(per.values(), []))]}
    out["denials_by_tool"] = dict(den.most_common())
    print("confirmations p95/p99/max:", {k: (v["p95"], v["p99"], v["max"]) for k, v in out["confirmations_dist"].items()})
    print("remaining denials by tool (3 passes):", out["denials_by_tool"])
    name = os.environ.get("OUT") or ("live_o4mini_paired.json" if EXCLUDE else "live_o4mini_paired_97.json")
    json.dump(out, open(os.path.join(R, name), "w"), indent=1)
    return out


if __name__ == "__main__":
    main()
