"""Stage 0 task selection (fixed before any run). Per suite, the first 5 user tasks (by number)
that (1) o4-mini solved undefended in all three recorded passes (live_o4mini, undef2, undef3) and
(2) whose ground truth passes at least one target value (e-mail, IBAN, URL, or an id argument:
id / file_id / event_id / email_id) that the request does not contain — a value the agent must take
from a tool output, so references are exercised. slack user_task_4 excluded (EXCLUSIONS.md).
Fewer than 5 such tasks (banking 3, travel 0) — filled, also fixed before any run, from tier 2: solved
in all three passes and the ground truth passes any target value (also one the request contains);
then tier 3: solved in all three passes. Tier recorded per task.

    python select_tasks.py  -> tasks.json
"""
import glob
import json
import os
import re

from agentdojo.task_suite.load_suites import get_suite

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "..", "results")
LINE = re.compile(r"\[UNDEFENDED ?\]\s+(\S+)\s+\(benign\)\s+utility=([Yn])")
TOK = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|(?:https?://|www\.)\S+")
IDS = {"id", "id_", "file_id", "event_id", "email_id"}


def solved(suite):
    passes = [glob.glob(os.path.join(R, "live_o4mini", f"benign_{suite}_undefended_*.log")),
              glob.glob(os.path.join(R, "live_grants", "undef2", f"{suite}_*.log")),
              glob.glob(os.path.join(R, "live_grants", "undef3", f"{suite}_*.log"))]
    sets = []
    for files in passes:
        ok = set()
        for f in files:
            ok |= {m.group(1) for m in LINE.finditer(open(f).read()) if m.group(2) == "Y"}
        sets.append(ok)
    return set.intersection(*sets)


def targets(call):
    out = []
    for k, v in call.args.items():
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if k in IDS and x is not None:
                out.append(str(x))
            elif isinstance(x, str):
                out += TOK.findall(x)
    return out


def main():
    sel = {}
    for s in ("banking", "slack", "travel", "workspace"):
        suite = get_suite("v1", s)
        ok = solved(s)
        tiers = {1: [], 2: [], 3: []}
        for tid in sorted(suite.user_tasks, key=lambda t: int(t.split("_")[-1])):
            if tid not in ok or (s, tid) == ("slack", "user_task_4"):
                continue
            ut = suite.user_tasks[tid]
            env = ut.init_environment(suite.load_and_inject_default_environment({}))
            gt = ut.ground_truth(env.model_copy(deep=True))
            allv = [v for c in gt for v in targets(c)]
            t = 1 if [v for v in allv if v not in ut.PROMPT] else 2 if allv else 3
            tiers[t].append(tid)
        picked = [(t, tid) for t in (1, 2, 3) for tid in tiers[t]][:5]
        sel[s] = [{"task": tid, "tier": t} for t, tid in picked]
        print(s, picked)
    json.dump(sel, open(os.path.join(HERE, "tasks.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
