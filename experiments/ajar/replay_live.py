"""Re-decide the recorded live o4-mini trajectories with a given kernel (no model).

    AXOR_CORE_REPO=<kernel> python replay_live.py <trajectories.tgz> <out.json>

Each governed trajectory (live v4: grants+L4, live v5: grants no-human) is replayed
call by call through a fresh ToolCallGovernor built exactly as the live runner builds
it (config_rule/<suite>.yaml, context integrity, request-only, R0 grant args, L1+L2s
grants from the request, NO confirmer): every recorded call is evaluated and, if it
was executed in the recording, its recorded output is registered (and its grant use
spent if the replay admits it). The verdict is "admitted without a human". Two
kernels (the quote rule, revision 4) are diffed by diff_live().
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import sys
import tarfile

CORE = os.environ["AXOR_CORE_REPO"]
sys.path.insert(0, CORE)
HERE = os.path.dirname(os.path.abspath(__file__))

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

sys.path.insert(0, HERE)
import axor_ajar  # noqa: E402  (agent_args / present / spend_args: MODEL.md §9 references)

CONFIG_DIR = os.environ.get("AXOR_AJAR_CONFIG_DIR") or os.path.join(HERE, "config_rule")
R0 = json.load(open(os.environ.get("AXOR_AJAR_GRANT_ARGS") or os.path.join(HERE, "live", "grant_args_R0.json")))
GRANTS = os.environ.get("REPLAY_GRANTS", "1") == "1"  # 0: configuration (a), no grants
TPL = json.load(open(os.path.join(HERE, "live", "templates_L2s.json")))


def text_of(msg):
    c = msg.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("content", "") or "" for b in c if isinstance(b, dict))
    return str(c or "")


def parse_call(tc):
    if isinstance(tc, dict):
        return tc["function"], dict(tc["args"])
    if isinstance(tc, str) and tc.startswith("{'function'"):
        d = ast.literal_eval(tc)
        return d["function"], dict(d["args"])
    s = str(tc)
    fn = re.search(r"function='(\w+)'", s).group(1)
    args = ast.literal_eval(re.search(r"args=(\{.*?\}) id=", s, re.S).group(1))
    return fn, args


def governor(suite, prompt):
    cfg = GovernanceConfig.from_yaml(os.path.join(CONFIG_DIR, f"{suite}.yaml"))
    cfg = dataclasses.replace(cfg, integrity_default="context", integrity_origins="request-only")
    cfg = axor_ajar.hyp_overlay(cfg)  # §9.16 / §9.17 hypotheses (off unless AXOR_HYP)
    kw = cfg.as_governor_kwargs()
    if GRANTS:
        kw["grant_args"] = (dict(cfg.grant_args) if os.environ.get("AXOR_AJAR_GRANT_ARGS_FROM_CONFIG") == "1"
                            else R0.get(suite, {}))
        if TPL.get(suite) and os.environ.get("AXOR_AJAR_L2") != "tuple":
            kw["grant_templates"] = TPL[suite]
    g = ToolCallGovernor(**kw)
    g.register_task(prompt)
    if GRANTS:
        g.grants.from_request(prompt)
    return g


def _calls_of(msg):
    tcs = msg.get("tool_calls")
    if isinstance(tcs, str):
        tcs = ast.literal_eval(tcs) if tcs not in ("None", "") else []
    return tcs or []


def replay(d):
    msgs = d["messages"]
    prompt = next(text_of(x) for x in msgs if x["role"] == "user")
    g = governor(d["suite"], prompt)
    outs = {x.get("tool_call_id"): x for x in msgs if x["role"] == "tool"}
    calls = []
    reads = ""  # recorded outputs before the current call (kept for denied calls: the audit)
    for x in msgs:
        if x["role"] != "assistant":
            continue
        for tc in _calls_of(x):
            fn, args = parse_call(tc)
            tid = tc.get("id") if isinstance(tc, dict) else re.search(r"id='([^']+)'", str(tc)).group(1)
            dec = g.evaluate(fn, axor_ajar.agent_args(g, dict(args)))
            rec = outs.get(tid) or {}
            executed = "governance kernel" not in str(rec.get("error")) and rec.get("error") in (None, "None")
            recorded_allowed = "governance kernel" not in str(rec.get("error"))
            if dec.allowed and getattr(dec, "grant_id", None) is not None:
                k = g.spend(dec, axor_ajar.spend_args(dec, dict(args)))
                if k is not None:
                    g.grant_store.commit(k)
            calls.append({"tool": fn, "args": args, "allowed": bool(dec.allowed), "category": dec.category,
                          "origins": list(getattr(dec, "reference_origins", ()) or ()),
                          "description": getattr(dec, "description", None),
                          "reason": (dec.reason or "")[:200], "recorded_allowed": recorded_allowed,
                          **({} if dec.allowed else {"reads_before": reads})})
            if executed:
                try:
                    axor_ajar.present(g, dec, text_of(rec), fn, axor_ajar.spend_args(dec, dict(args)))
                except Exception:
                    pass
                reads += "\n" + text_of(rec)
    return {"suite": d["suite"], "task": d["user_task_id"], "utility": d["utility"], "prompt": prompt, "calls": calls}


def main_benign(root, out):
    """The 288 recorded benign AgentDojo trajectories (3 models x 96 tasks)."""
    import glob
    res = []
    for model in ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"):
        for suite in ("banking", "slack", "travel", "workspace"):
            for p in sorted(glob.glob(os.path.join(root, model, suite, "user_task_*", "none", "none.json"))):
                d = json.load(open(p))
                if (suite, d["user_task_id"]) == ("slack", "user_task_4"):
                    continue
                d["suite"] = suite
                r = replay(d)
                r["pass"] = model
                res.append(r)
    json.dump(res, open(out, "w"), indent=1, default=str)
    print(out, len(res), "trajectories,", sum(len(r["calls"]) for r in res), "calls")


def main(path, out):
    if os.path.isdir(path):
        return main_benign(path, out)
    tf = tarfile.open(path)
    res = []
    for m in sorted(tf.getmembers(), key=lambda m: m.name):
        if not m.name.endswith(".json"):
            continue
        d = json.load(tf.extractfile(m))
        if (d["suite"], d["user_task_id"]) == ("slack", "user_task_4"):
            continue
        r = replay(d)
        r["pass"] = m.name.split("/")[1]
        res.append(r)
    json.dump(res, open(out, "w"), indent=1, default=str)
    print(out, len(res), "trajectories,", sum(len(r["calls"]) for r in res), "calls")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
