"""Summarise the live o4-mini runs with task-scoped grants (one directory per pass).

    python live_grants_summary.py /home/user/ext/live_grants pass1 pass2 pass3 [nogrants]

Undefended baselines are the paper's 7-pass numbers (not re-run).
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter

SUITES = ("banking", "slack", "travel", "workspace")
N_TASKS = {"banking": 16, "slack": 21, "travel": 20, "workspace": 40}
UNDEFENDED = {"banking": 67.9, "slack": 84.8, "travel": 62.5, "workspace": 84.3}
BENIGN = re.compile(r"\[GOVERNED ?\]\s+(\S+)\s+\(benign\)\s+utility=([Yn])")
DENIALS = re.compile(r"benign denials:\s+(\d+)\s+\((\[.*\])\)")
CONF = re.compile(r"confirmations:\s+(\d+) over (\d+) tasks")


def read_pass(d: str) -> dict:
    out = {}
    for s in SUITES:
        ok = n = conf = 0
        den: Counter = Counter()
        for path in glob.glob(os.path.join(d, f"{s}_*.log")):
            text = open(path).read()
            for m in BENIGN.finditer(text):
                n += 1
                ok += m.group(2) == "Y"
            dm = DENIALS.search(text)
            if dm:
                for item in ast.literal_eval(dm.group(2)):
                    den[item] += 1
            cm = CONF.search(text)
            if cm:
                conf += int(cm.group(1))
        out[s] = {"ok": ok, "n": n, "confirmations": conf, "denials": dict(den)}
    return out


def main(root: str, passes: list[str]) -> dict:
    data = {p: read_pass(os.path.join(root, p)) for p in passes}
    grant_passes = [p for p in passes if p.startswith("pass")]
    res: dict = {"passes": data, "suites": {}}
    print(f"{'suite':10s} {'undef (paper)':>13s} {'grants+L4':>16s} {'cost':>8s} {'conf/task':>10s}"
          + ("  no grants" if "nogrants" in data else ""))
    tot_util = []
    for s in SUITES:
        utils = [100 * data[p][s]["ok"] / data[p][s]["n"] for p in grant_passes if data[p][s]["n"]]
        complete = all(data[p][s]["n"] == N_TASKS[s] for p in grant_passes)
        conf = [data[p][s]["confirmations"] / N_TASKS[s] for p in grant_passes]
        mean = statistics.mean(utils) if utils else float("nan")
        sd = statistics.stdev(utils) if len(utils) > 1 else 0.0
        ng = ""
        if "nogrants" in data and data["nogrants"][s]["n"]:
            ng = f"  {100 * data['nogrants'][s]['ok'] / data['nogrants'][s]['n']:.1f}%"
        print(f"{s:10s} {UNDEFENDED[s]:>12.1f}% {mean:>8.1f}% ± {sd:4.1f} {mean - UNDEFENDED[s]:>+7.1f} "
              f"{statistics.mean(conf):>9.2f}{'' if complete else ' (incomplete)'}{ng}")
        res["suites"][s] = {"utility_mean": mean, "utility_sd": sd, "per_pass": utils,
                            "undefended_paper": UNDEFENDED[s], "confirmations_per_task": statistics.mean(conf)}
    per_pass_total = [100 * sum(data[p][s]["ok"] for s in SUITES) / sum(data[p][s]["n"] for s in SUITES)
                      for p in grant_passes]
    und = sum(UNDEFENDED[s] * N_TASKS[s] for s in SUITES) / sum(N_TASKS.values())
    conf_all = statistics.mean(sum(data[p][s]["confirmations"] for s in SUITES) / 97 for p in grant_passes)
    m = statistics.mean(per_pass_total)
    sd = statistics.stdev(per_pass_total) if len(per_pass_total) > 1 else 0.0
    print(f"{'all 97':10s} {und:>12.1f}% {m:>8.1f}% ± {sd:4.1f} {m - und:>+7.1f} {conf_all:>9.2f}")
    res["all"] = {"utility_mean": m, "utility_sd": sd, "per_pass": per_pass_total,
                  "undefended_paper_weighted": und, "confirmations_per_task": conf_all}
    den = Counter()
    for p in grant_passes:
        for s in SUITES:
            den.update(data[p][s]["denials"])
    print("\ndenials over the grant passes:", dict(den.most_common()))
    res["denials"] = dict(den)
    return res


if __name__ == "__main__":
    out = main(sys.argv[1], sys.argv[2:])
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "live_o4mini_grants.json")
    json.dump(out, open(path, "w"), indent=1)
