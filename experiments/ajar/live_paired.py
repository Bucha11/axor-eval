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
PAPER = {"banking": 67.9, "slack": 84.8, "travel": 62.5, "workspace": 84.3}
LINE = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+)\s+\(benign\)\s+utility=([Yn])")
# A task whose run raised (e.g. AgentDojo's own KeyError on slack user_task_4 when
# the agent posts to a page the environment does not have) counts as a failure, so
# every pass has the full denominator.
ERR = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+): ERROR")


def count(paths: list[str]) -> tuple[int, int]:
    ok = n = 0
    for p in paths:
        text = open(p).read()
        for m in LINE.finditer(text):
            n += 1
            ok += m.group(3) == "Y"
        n += len(ERR.findall(text))
    return ok, n


def passes() -> tuple[list[dict], list[dict]]:
    und = [{s: count(glob.glob(os.path.join(R, "live_o4mini", f"benign_{s}_undefended_*.log"))) for s in SUITES}]
    for d in ("undef2", "undef3"):
        und.append({s: count(glob.glob(os.path.join(R, "live_grants", d, f"{s}_*.log"))) for s in SUITES})
    gov = [{s: count(glob.glob(os.path.join(R, "live_grants", d, f"{s}_*.log"))) for s in SUITES}
           for d in ("pass1", "pass2", "pass3")]
    return und, gov


def pct(c):
    return 100 * c[0] / c[1] if c[1] else float("nan")


def main() -> dict:
    und, gov = passes()
    out = {"undefended": und, "governed": gov, "rows": {}}
    hdr = f"{'suite':10s} {'undefended (3)':>18s} {'grants+L4 (3)':>18s} {'paired cost':>15s} {'vs paper':>10s}"
    print(hdr)
    rows = list(SUITES) + ["all"]
    for s in rows:
        if s == "all":
            u = [100 * sum(p[x][0] for x in SUITES) / sum(p[x][1] for x in SUITES) for p in und]
            g = [100 * sum(p[x][0] for x in SUITES) / sum(p[x][1] for x in SUITES) for p in gov]
            paper = sum(PAPER[x] * N[x] for x in SUITES) / sum(N.values())
            complete = all(sum(p[x][1] for x in SUITES) == 97 for p in und + gov)
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
               "complete": complete}
        out["rows"][s] = row
        print(f"{s:10s} {row['undefended_mean']:>9.1f}% ± {row['undefended_sd']:4.1f} "
              f"{row['governed_mean']:>9.1f}% ± {row['governed_sd']:4.1f} "
              f"{row['paired_mean']:>+8.1f} ± {row['paired_sd']:4.1f} {row['unpaired_vs_paper']:>+9.1f}"
              f"{'' if complete else '  (incomplete)'}")
    json.dump(out, open(os.path.join(R, "live_o4mini_paired.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    main()
