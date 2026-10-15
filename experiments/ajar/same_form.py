"""MODEL.md §9.15 evaluation: attacks of the same form with another value.

An attacker call whose sink and argument carry a description grant in that session (the request
described the target there) but whose value differs from the computed one: is it admitted without a
human? Also: landed attacks with a call admitted on a description grant (an attack through the
description itself).

    Ajar: every attacker-seeded probe (mode b, grants without L4).
    Replay: the 1887 recorded attack runs (variant R0 L1+L2s, no human).

    AXOR_AJAR_CONFIG_DIR=config_m1_c9v4 AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 \
    AXOR_CORE_REPO=... python same_form.py OUT.json
"""
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_opl  # noqa: E402
import replay_runs  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import Verdict  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

REC: list = []
_orig = ToolCallGovernor.evaluate


def _leaves(v):
    return v if isinstance(v, (list, tuple)) else [v]


def _eval(self, tool, args):
    d = _orig(self, tool, args)
    args_r = d.resolved_args if getattr(d, "resolved_args", None) is not None else args
    other = []
    for (sink, arg), vals in getattr(self, "_described", {}).items():
        if sink != tool:
            continue
        for x in _leaves(args_r.get(arg)):
            if x not in (None, "") and str(x).strip().casefold() not in vals:
                other.append({"arg": arg, "value": str(x), "described": sorted(vals)})
    REC.append({"tool": tool, "allowed": bool(d.allowed), "category": d.category,
                "description": getattr(d, "description", None), "other": other})
    return d


ToolCallGovernor.evaluate = _eval


def ajar():
    d = paper_opl.make("grants:L1+L2s:R0")
    res = Counter()
    attacks, admitted_attacks, rows = set(), set(), []
    for spec, probes in run_ajar.load(None):
        for p in probes:
            if p.fault_class.value != "ATTACKER_SEEDED" or not p.scored:
                continue
            REC.clear()
            v = d.decide(spec, p.context, p.candidate)
            last = REC[-1]
            if last["other"]:
                aid = (str(spec.task), p.ground_truth.get("injection_id") or p.probe_id.split("-k")[0])
                res["probes"] += 1
                res["admitted"] += v is Verdict.ALLOW
                attacks.add(aid)
                if v is Verdict.ALLOW:
                    admitted_attacks.add(aid)
                rows.append({"task": str(spec.task), "probe": p.probe_id, "tool": last["tool"],
                             "other": last["other"], "allowed": v is Verdict.ALLOW, "category": last["category"]})
            if v is Verdict.ALLOW and last["description"]:
                res["admitted_on_a_description"] += 1
    return {"probes_same_form_other_value": res["probes"], "of_them_admitted": res["admitted"],
            "attacks_same_form_other_value": len(attacks), "attacks_admitted": len(admitted_attacks),
            "attacker_probes_admitted_on_a_description_grant": res["admitted_on_a_description"],
            "categories": Counter(r["category"] for r in rows).most_common(), "rows": rows}


def replay():
    V = replay_runs.variants()["R0 L1+L2s"]
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
    res, rows = Counter(), []
    for model in ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"):
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = replay_runs.get_suite(replay_runs.VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", "important_instructions",
                                                      "*.json"))):
                run = json.load(open(path))
                REC.clear()
                try:
                    util, sec = replay_runs.replay(V, suite, run)
                except Exception:
                    res["errors"] += 1
                    continue
                res["runs"] += 1
                same = [r for r in REC if r["other"]]
                desc = [r for r in REC if r["allowed"] and r["description"]]
                res["calls_same_form_other_value"] += len(same)
                res["of_them_admitted"] += sum(r["allowed"] for r in same)
                res["runs_with_such_a_call"] += bool(same)
                res["runs_with_a_description_grant_used"] += bool(desc)
                res["landed_with_a_description_grant_used"] += bool(sec and desc)
                res["landed"] += bool(sec)
                if same or desc:
                    rows.append({"model": model, "suite": sname, "task": run["user_task_id"],
                                 "injection": run.get("injection_task_id"), "landed": bool(sec), "utility": util,
                                 "same_form": same, "description_calls": desc})
    return {**dict(res), "rows": rows}


def main(out):
    a = ajar()
    print("ajar", json.dumps({k: v for k, v in a.items() if k != "rows"}), flush=True)
    r = replay()
    print("replay", json.dumps({k: v for k, v in r.items() if k != "rows"}), flush=True)
    json.dump({"ajar": a, "replay": r}, open(out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
