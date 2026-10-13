"""Replay of the 1887 attacked trajectories: attacks (c)-naive admits beyond (c)-oracle,
and on which tools — the calls naive confirmed (L4) that oracle refused.

    AXOR_CORE_REPO=... AXOR_AJAR_CONFIG_DIR=.../config_rule python naive_vs_oracle.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_runs as RR  # noqa: E402

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from ajar.core.types import Candidate  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402

MODELS = ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18")


def replay(variant, suite, run):
    """replay_runs.replay, also returning the L4-confirmed calls that executed."""
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = suite.load_and_inject_default_environment(dict(run.get("injections") or {}))
    env = ut.init_environment(env)
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    g = RR.factory(variant, suite, prompt, plan)()
    g.register_task(prompt)
    executed, confirmed = [], []
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    for c in calls:
        d = g.evaluate(c["function"], dict(c["args"]))
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, dict(c["args"]))
            if key is not None:
                g.grant_store.commit(key)
        if getattr(d, "grant_source", None) == "L4":
            confirmed.append((c["function"], dict(c["args"])))
        res, err = runtime.run_function(env, c["function"], dict(c["args"]))
        executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
        if err is None:
            g.register_output(d, tool_result_to_str(res))
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    sec = bool(suite._check_injection_task_security(inj, [], pre, env, executed)) if inj else None
    return sec, confirmed


def main():
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
    V = RR.variants()
    naive, oracle = V["R0 L1+L2s+L4 naive"], V["R0 L1+L2s+L4 oracle"]
    extra, tools, rows = 0, Counter(), []
    tot = {"naive": 0, "oracle": 0, "runs": 0}
    for model in MODELS:
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = get_suite(VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(path))
                sn, conf = replay(naive, suite, run)
                so, _ = replay(oracle, suite, run)
                tot["runs"] += 1
                tot["naive"] += int(bool(sn))
                tot["oracle"] += int(bool(so))
                if sn and not so:
                    extra += 1
                    ts = sorted({t for t, _ in conf})
                    tools.update(ts or ["<none confirmed>"])
                    rows.append({"model": model, "suite": sname, "user_task": run["user_task_id"],
                                 "injection_task": run.get("injection_task_id"), "confirmed": conf})
    out = {"totals": tot, "naive_beyond_oracle": extra, "by_confirmed_tool": dict(tools.most_common()),
           "by_injection": dict(Counter(f"{r['suite']}/{r['injection_task']}" for r in rows).most_common()),
           "rows": rows}
    json.dump(out, open(os.path.join(HERE, "results", "residuals_naive_vs_oracle_v3.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
