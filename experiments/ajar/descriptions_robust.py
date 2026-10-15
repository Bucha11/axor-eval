"""MODEL.md §9.15 evaluation, template robustness (no model).

    fired  OUT.json             — per task: the descriptions computed (phrase, sink, arg, value) along
                                  the Ajar reference plan and along the 288 recorded benign trajectories
    robust PARAPHRASES.json OUT — the same plan / trajectories with the request replaced by each
                                  hand-written paraphrase: is the description still built, and right?

"Right" = the value the Ajar reference plan passes at that (sink, argument) of the task. A value
built for a (sink, argument) that differs from it is a false description.

    AXOR_AJAR_CONFIG_DIR=config_m1_c9v4 AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 \
    AXOR_CORE_REPO=... python descriptions_robust.py fired|robust ...
"""
from __future__ import annotations

import copy
import dataclasses
import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import paper_opl  # noqa: E402
import replay_live  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import ContextRef  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

LOG: list = []
_orig = ToolCallGovernor.observe_structured


def _obs(self, tool, args, value):
    new = _orig(self, tool, args, value)
    LOG.extend(new)
    return new


ToolCallGovernor.observe_structured = _obs
RUNS = os.environ.get("AXOR_RUNS", "/home/user/Ajar/bench/agentdojo/runs")


def canon(v):
    return str(v).strip().casefold()


TRUTH = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "descriptions_truth.json")))


def plan_values(spec):
    """The task's right values: every value its reference plan passes, plus, for the travel
    recommendation tasks, the expected entities (descriptions_truth.json)."""
    out = set()
    cfg = axor_ajar.load_config(spec.task.suite, "context", "request-only")
    sinks = set(cfg.driving_args) | set(cfg.egress_sinks) | set(cfg.integrity_sinks)
    for c in spec.plan:
        if c.tool not in sinks:
            continue  # a read's arguments (a list of hotels to rate) are not what the task targets
        for a, v in dict(c.args).items():
            for x in (v if isinstance(v, list) else [v]):
                out.add(canon(x))
    key = f"{spec.task.suite}/{str(spec.task).split('/')[2].split('@')[0]}"
    return out | {canon(x) for x in TRUTH.get(key, ())}


def walk_plan(spec, prompt):
    d = paper_opl.make("grants:L1+L2s:R0")
    spec = dataclasses.replace(spec, prompt=prompt)
    LOG.clear()
    axor_ajar.plan_walk(d, spec)
    return list(LOG)


def benign(suite, task):
    for model in ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"):
        p = os.path.join(RUNS, model, suite, task, "none", "none.json")
        if os.path.exists(p):
            d = json.load(open(p))
            d["suite"] = suite
            yield model, d


def walk_benign(d, prompt):
    d = copy.deepcopy(d)
    for m in d["messages"]:
        if m["role"] == "user":
            m["content"] = prompt if not isinstance(m["content"], list) else [{"type": "text", "content": prompt}]
            break
    LOG.clear()
    r = replay_live.replay(d)
    return list(LOG), r


def tasks():
    return {(spec.task.suite, str(spec.task).split("/")[2].split("@")[0]): spec for spec, _ in run_ajar.load(None)}


def judge(built, truth):
    """built: [(phrase, sink, arg, values)] -> {(sink,arg): (values, right?)}"""
    res = {}
    for phrase, sink, arg, vals in built:
        right = all(canon(v) in truth for v in vals)
        res[f"{sink}.{arg}"] = {"phrase": phrase, "values": [str(v) for v in vals], "right": right}  # every value is one the task needs
    return res


def fired(out):
    rows = {}
    for (suite, task), spec in sorted(tasks().items()):
        truth = plan_values(spec)
        plan = judge(walk_plan(spec, spec.prompt), truth)
        ben = {}
        for model, d in benign(suite, task):
            log, _ = walk_benign(d, spec.prompt)
            ben[model] = judge(log, truth)
        if plan or any(ben.values()):
            rows[f"{suite}/{task}"] = {"prompt": spec.prompt, "plan": plan, "benign": ben}
            print(suite, task, json.dumps({"plan": plan, "benign": ben})[:400], flush=True)
    json.dump(rows, open(out, "w"), indent=1)


def robust(par_path, out):
    pars = json.load(open(par_path))
    T = tasks()
    rows, tot = {}, defaultdict(int)
    for key, ps in ((k, v) for k, v in pars.items() if not k.startswith("_")):
        suite, task = key.split("/")
        spec = T[(suite, task)]
        truth = plan_values(spec)
        base_plan = judge(walk_plan(spec, spec.prompt), truth)
        base_ben = {m: judge(walk_benign(d, spec.prompt)[0], truth) for m, d in benign(suite, task)}
        rows[key] = {"prompt": spec.prompt, "base": {"plan": base_plan, "benign": base_ben}, "paraphrases": []}
        for p in ps:
            got_plan = judge(walk_plan(spec, p), truth)
            got_ben = {m: judge(walk_benign(d, p)[0], truth) for m, d in benign(suite, task)}
            # per walk (the plan and each recorded trajectory) where the original built a description:
            # still built and right / not built / false (built, but not the right value)
            verdicts = []
            for base, got in [(base_plan, got_plan)] + [(base_ben[m], got_ben.get(m, {})) for m in base_ben]:
                for sa, b in base.items():
                    g = got.get(sa)
                    v = "not built" if g is None else "built and right" if g["right"] else "false"
                    v = v if b["right"] else f"base false: {v}"  # the original was already false
                    verdicts.append(v)
                    tot[v] += 1
                for sa, g in got.items():  # a new description the original did not build
                    if sa not in base and g["right"] is False:
                        verdicts.append("false (new)")
                        tot["false (new)"] += 1
            rows[key]["paraphrases"].append({"text": p, "plan": got_plan, "benign": got_ben, "verdicts": verdicts})
            print(key, "|", p[:70], "|", verdicts, flush=True)
    n = tot["built and right"] + tot["not built"] + tot["false"]  # originals that were right
    summ = {"walks_with_a_right_original": n, **dict(tot),
            "share_built_and_right": round(tot["built and right"] / n, 3) if n else None,
            "share_false": round(tot["false"] / n, 3) if n else None}
    # per (task, paraphrase): right in every walk / in some / not built / false (a wrong value built)
    units = Counter()
    for key, r in rows.items():
        for p in r["paraphrases"]:
            vs = set(p["verdicts"])
            st = ("false" if vs & {"false", "false (new)", "base false: false"} else
                  "original false, not built" if vs and all(v.startswith("base false") for v in vs) else
                  "built and right (all walks)" if vs == {"built and right"} else
                  "built and right (some walks / targets)" if "built and right" in vs else
                  "no description in the original either" if not vs else "not built")
            p["unit"] = st
            units[st] += 1
    summ["units"] = dict(units)
    print(json.dumps(summ))
    json.dump({"summary": summ, "rows": rows}, open(out, "w"), indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "fired":
        fired(sys.argv[2])
    else:
        robust(sys.argv[2], sys.argv[3])
