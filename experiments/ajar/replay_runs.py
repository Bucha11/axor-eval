"""Replay recorded attacked runs through axor (no model): would the attack have landed?

AgentDojo ships real model trajectories under attack (`runs/<model>/<suite>/<user
task>/<attack>/<injection task>.json`). Each is replayed through the same loop as
axor-core's live `GovernedToolsExecutor` (evaluate → run if allowed → register the
output), plus the grant spend, in a fresh environment with the run's injections loaded; a
denied call is not executed, the next logged call is tried. Then AgentDojo's own
predicates grade the end state:

  ASR      the injection task's security() — did the attacker's effect happen
  utility  the user task's utility() on the replayed state (a LOWER bound for a
           defended agent: a live model would react to a denial, a replay cannot)

This is replay, not a live run: a model that sees a denial might try another path.
It answers "on the paths real models actually took, which effects would axor have
executed", the same question as the E6 replay plan, on AgentDojo's own corpus.

    python replay_runs.py --model gpt-4o-2024-05-13 --attack important_instructions
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import axor_ajar  # noqa: E402

from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

from check_wrapper import VERSIONS  # noqa: E402


def variants():
    return {
        "none": None,
        "axor-clean": ("clean", None),
        "axor-ctx-request-only": ("ctx", None),
        "grants-L1": ("ctx", "L1"),
        "grants-L1+L2s+L4": ("ctx", "L1+L2s+L4"),
        "grants-L1+L4": ("ctx", "L1+L4"),
        "v2 grants-L1+L2s+L4": ("ctx", "L1+L2s+L4", "v2"),
        "v2 grants-L1+L4": ("ctx", "L1+L4", "v2"),
        # schema-derived grant args (derive_grants R0); run with AXOR_AJAR_CONFIG_DIR
        # pointing at config_rule/ for the rule taxonomy
        "R0 L1+L2s": ("ctx", "L1+L2s", "R0"),
        "R0 L1+L2s+L4 oracle": ("ctx", "L1+L2s+L4", "R0", "oracle"),
        "R0 L1+L2s+L4 naive": ("ctx", "L1+L2s+L4", "R0", "naive"),
        "R0 L1+L2s+L4 view": ("ctx", "L1+L2s+L4", "R0", "view"),
        # allowlist control: the known-payee template WITH the attacker IBAN US133…
        "R0 L1+L2": ("ctx", "L1+L2", "R0"),
        "R0 L1+L2+L4 oracle": ("ctx", "L1+L2+L4", "R0", "oracle"),
    }


def factory(variant, suite, prompt, plan):
    base, levels = variant[0], variant[1]
    tag = variant[2] if len(variant) > 2 else None
    confirm = variant[3] if len(variant) > 3 else "oracle"
    if tag == "R0":
        ga = _r0_table()
    else:
        ga = axor_ajar.GRANT_ARGS_V2 if tag == "v2" else None
    integrity = (None, "any-trusted") if base == "clean" else ("context", "request-only")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite.name), prompt=prompt, plan=plan)

    def make():
        cfg = axor_ajar.load_config(suite.name, *integrity)
        kw = cfg.as_governor_kwargs()
        if levels:
            kwargs, hook = axor_ajar.grants_kwargs(levels, grant_args=ga, confirm=confirm)
            kw.update(kwargs(spec))
            g = ToolCallGovernor(**kw)
            hook(g, spec)
        else:
            g = ToolCallGovernor(**kw)
        return g

    return make


_R0 = None


def _r0_table():
    global _R0
    if _R0 is None and os.environ.get("AXOR_AJAR_GRANT_ARGS"):
        _R0 = json.load(open(os.environ["AXOR_AJAR_GRANT_ARGS"]))
    if _R0 is None:
        import derive_grants as D
        from ajar import io, paths
        specs = io.load_specs(paths.benchmark_data_dir("agentdojo", None) / "tasks.jsonl")
        _R0 = D.derive(specs, D.rule_all_non_rich)
    return _R0


def replay(variant, suite, run):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = suite.load_and_inject_default_environment(dict(run.get("injections") or {}))
    env = ut.init_environment(env)
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    from ajar.core.types import Candidate
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    executed = []
    if variant is None:
        for c in calls:
            _, err = runtime.run_function(env, c["function"], dict(c["args"]))
            executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
    else:
        g = factory(variant, suite, prompt, plan)()
        g.register_task(prompt)
        from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
        for c in calls:
            d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
            if not d.allowed:
                continue
            if getattr(d, "grant_id", None) is not None:
                key = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
                if key is not None:
                    g.grant_store.commit(key)
            res, err = runtime.run_function(env, c["function"], dict(c["args"]))
            executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
            if err is None:
                axor_ajar.present(g, d, tool_result_to_str(res))
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    sec = None
    if inj is not None:
        sec = bool(suite._check_injection_task_security(inj, [], pre, env, executed))
    util = bool(suite._check_user_task_utility(ut, [], pre, env, executed))
    return util, sec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-4o-2024-05-13,claude-3-5-sonnet-20241022,gpt-4o-mini-2024-07-18")
    ap.add_argument("--attack", default="important_instructions")
    ap.add_argument("--suites", default="banking,slack,travel,workspace")
    ap.add_argument("--out", default=os.path.join(_HERE, "results", "replay.json"))
    ap.add_argument("--variants", default="", help="comma-separated subset (default: all)")
    a = ap.parse_args(argv)
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
    V = variants()
    if a.variants:
        V = {k: V[k] for k in a.variants.split(",")}
    agg = defaultdict(lambda: {"runs": 0, "attacks_landed": 0, "utility": 0, "errors": 0})
    for model in a.models.split(","):
        for sname in a.suites.split(","):
            suite = get_suite(VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", a.attack, "*.json"))):
                run = json.load(open(path))
                for name, v in V.items():
                    r = agg[(name, sname)]
                    try:
                        util, sec = replay(v, suite, run)
                    except Exception:  # a replay that cannot run is counted, never hidden
                        r["errors"] += 1
                        continue
                    r["runs"] += 1
                    r["attacks_landed"] += int(bool(sec))
                    r["utility"] += int(util)
    rows = {}
    for (name, sname), r in sorted(agg.items()):
        rows.setdefault(name, {})[sname] = r
    for name in V:
        tot = {k: sum(rows.get(name, {}).get(s, {}).get(k, 0) for s in a.suites.split(","))
               for k in ("runs", "attacks_landed", "utility", "errors")}
        rows.setdefault(name, {})["all"] = tot
        n = tot["runs"] or 1
        print(f"{name:24s} runs={tot['runs']:5d} ASR={tot['attacks_landed'] / n:.3f} "
              f"utility(replay)={tot['utility'] / n:.3f} errors={tot['errors']}")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"models": a.models, "attack": a.attack, "rows": rows}, open(a.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
