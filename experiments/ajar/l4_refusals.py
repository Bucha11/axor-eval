"""Live v4: classify the L4 oracle refusals — the governed calls the grant gate denied
after the oracle said no — against the task's reference plan.

    python l4_refusals.py results/live_v4/trajectories.tgz

For each denied call (category grant_gate), the closest plan call of the same tool is
found on the oracle's own projection (grant args, dates/times excepted, canonical
values); the differing args are reported. "reference typo" = every difference is an
e-mail the plan spells with AgentDojo's `@luesparrowtech.com` typo where the call has
`@bluesparrowtech.com`.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tarfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
from agentdojo.task_suite.load_suites import get_suites  # noqa: E402
from axor_core.kernel.handles import canonicalize, split_kind  # noqa: E402

R0 = json.load(open(os.path.join(HERE, "live", "grant_args_R0.json")))
TEMPORAL = re.compile(r"(date|time|day)", re.I)


def proj(kinds, args):
    out = {}
    for k, spec in kinds.items():
        if TEMPORAL.search(k):
            continue
        kind = split_kind(spec)[0]
        v = args.get(k)
        vals = v if isinstance(v, (list, tuple)) else ([] if v is None else [v])
        try:
            out[k] = tuple(sorted(canonicalize(kind, x) for x in vals))
        except ValueError:
            out[k] = ("<bad>",)
    return out


def parse_call(tc):
    if isinstance(tc, dict):
        return tc["function"], dict(tc["args"])
    m = re.match(r"function='([^']+)' args=(\{.*\}) id=", str(tc), re.S)
    return m.group(1), ast.literal_eval(m.group(2))


def main(path):
    tf = tarfile.open(path)
    suites = get_suites("v1")
    plans = {}
    rows, cls = [], Counter()
    for m in tf.getmembers():
        if not m.name.endswith(".json"):
            continue
        d = json.load(tf.extractfile(m))
        s, t = d["suite"], d["user_task_id"]
        if (s, t) not in plans:
            suite = suites[s]
            env = suite.load_and_inject_default_environment({})
            ut = suite.get_user_task_by_id(t)
            env = ut.init_environment(env)
            plans[(s, t)] = [(c.function, dict(c.args)) for c in ut.ground_truth(env)]
        for msg in d["messages"]:
            if msg.get("role") != "tool" or "(grant_gate)" not in str(msg.get("error")):
                continue
            tool, args = parse_call(msg["tool_call"])
            kinds = R0.get(s, {}).get(tool, {})
            got = proj(kinds, args)
            cands = [proj(kinds, a) for f, a in plans[(s, t)] if f == tool]
            if not cands:
                kind = "tool not in the plan"
                diff = {}
            elif got in cands:
                kind = "matches the plan (budget/dedup)"
                diff = {}
            elif any(all(tuple(sorted(x.replace("@luesparrowtech", "@bluesparrowtech") for x in c.get(k, ())))
                             == got.get(k, ()) for k in set(c) | set(got)) for c in cands):
                kind = "reference typo"
                diff = {}
            else:
                best = min(cands, key=lambda c: sum(c.get(k) != got.get(k) for k in set(c) | set(got)))
                diff = {k: {"plan": best.get(k), "call": got.get(k)} for k in set(best) | set(got)
                        if best.get(k) != got.get(k)}
                typo = diff and all(
                    any("luesparrowtech" in x and "bluesparrowtech" not in x for x in (v["plan"] or ()))
                    and sorted(x.replace("@luesparrowtech", "@bluesparrowtech") for x in v["plan"]) == sorted(v["call"] or ())
                    for v in diff.values())
                kind = "reference typo" if typo else ("args differ: " + ",".join(sorted(diff)) if diff
                                                       else "matches the plan (budget/dedup)")
            cls[kind] += 1
            rows.append({"pass": m.name.split("/")[1], "suite": s, "task": t, "tool": tool, "class": kind,
                         "diff": {k: {kk: list(vv or ()) for kk, vv in v.items()} for k, v in diff.items()}})
    out = {"grant_gate_denials": len(rows), "by_class": dict(cls.most_common()),
           "by_task": dict(Counter(f"{r['suite']}/{r['task']}" for r in rows).most_common()), "rows": rows}
    json.dump(out, open(os.path.join(HERE, "results", "live_v4_l4_refusals.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
