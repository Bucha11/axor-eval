"""The E0 gate: does the Ajar wrapper reproduce the live executor's verdicts?

The wrapper rebuilds the governor's state from scratch for every decision (fresh
governor, the task prompt, the executed prefix re-run and registered). The live
path is axor-core's own `GovernedToolsExecutor`, which keeps one governor for the
whole conversation. If the two ever disagree on a call, E1's numbers mean nothing.

No model is called: the "live" run replays real model trajectories from AgentDojo's
shipped runs corpus (`bench/agentdojo/runs/<model>/<suite>/...`) through the real
executor in a real AgentDojo environment with the run's injections loaded. A call
the executor denies is not executed, exactly as live; the scripted model simply
continues with the next logged call.

    python check_wrapper.py --model gpt-4o-2024-05-13 --suite banking
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import axor_ajar  # noqa: E402  (sys.path for axor-core)

sys.path.insert(0, os.path.join(axor_ajar._CORE, "examples", "agentdojo"))

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo_adapter import GovernedToolsExecutor  # noqa: E402

VERSIONS = {"banking": "v1.2.2", "workspace": "v1.2.2", "slack": "v1.2", "travel": "v1.2"}


def fresh_env(suite, user_task, injections):
    env = suite.load_and_inject_default_environment(dict(injections))
    return user_task.init_environment(env)


def live_verdicts(defense, suite, user_task, prompt, injections, calls):
    """axor-core's GovernedToolsExecutor over the logged calls, one turn per call."""
    ex = GovernedToolsExecutor(lambda: _governor(defense, suite.name, prompt))
    runtime = FunctionsRuntime(suite.tools)
    env = fresh_env(suite, user_task, injections)
    messages = [{"role": "user", "content": prompt}]
    out = []
    for i, c in enumerate(calls):
        fc = FunctionCall(function=c["function"], args=dict(c["args"]), id=f"c{i}")
        messages.append({"role": "assistant", "content": None, "tool_calls": [fc]})
        denied_before = ex.denied_count
        _, _, env, messages, _ = ex.query(prompt, runtime, env, messages)
        out.append(ex.denied_count == denied_before)
    return out


def _governor(defense, suite_name, prompt):
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite_name), prompt=prompt, plan=())
    cfg = axor_ajar.load_config(suite_name, defense.integrity_default, defense.integrity_origins)
    from axor_core.governor import ToolCallGovernor
    return ToolCallGovernor(**cfg.as_governor_kwargs())


def wrapper_verdicts(defense, suite, user_task, prompt, injections, calls):
    """The wrapper's construction: per decision, a fresh governor fed the prefix of
    calls that actually executed."""
    runtime = FunctionsRuntime(suite.tools)
    executed: list = []  # (call, output or None)
    out = []
    for c in calls:
        g = _governor(defense, suite.name, prompt)
        g.register_task(prompt)
        for pc, pout in executed:
            d = g.evaluate(pc["function"], dict(pc["args"]))
            if pout is not None:
                g.register_output(d, pout)
        allowed = g.evaluate(c["function"], dict(c["args"])).allowed
        out.append(allowed)
        if allowed:
            env = fresh_env(suite, user_task, injections)
            for pc, _ in executed:
                runtime.run_function(env, pc["function"], dict(pc["args"]))
            res, err = runtime.run_function(env, c["function"], dict(c["args"]))
            executed.append((c, None if err is not None else tool_result_to_str(res)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4o-2024-05-13")
    ap.add_argument("--suite", default="banking")
    ap.add_argument("--attacks", default="none,important_instructions")
    a = ap.parse_args(argv)
    suite = get_suite(VERSIONS[a.suite], a.suite)
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs", a.model, a.suite)
    defenses = [d for d in __import__("run_ajar").e0_defenses()]
    report = {d.name: {"runs": 0, "calls": 0, "mismatches": 0, "denied": 0} for d in defenses}
    examples = []
    for path in sorted(glob.glob(os.path.join(root, "user_task_*", "*", "*.json"))):
        attack = path.split(os.sep)[-2]
        if attack not in a.attacks.split(","):
            continue
        run = json.load(open(path))
        ut = suite.user_tasks[run["user_task_id"]]
        prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
        if isinstance(prompt, list):
            prompt = "".join(b.get("content", "") for b in prompt)
        calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
        if not calls:
            continue
        inj = run.get("injections") or {}
        for d in defenses:
            lv = live_verdicts(d, suite, ut, prompt, inj, calls)
            wv = wrapper_verdicts(d, suite, ut, prompt, inj, calls)
            r = report[d.name]
            r["runs"] += 1
            r["calls"] += len(calls)
            r["denied"] += sum(1 for x in lv if not x)
            mm = [i for i, (x, y) in enumerate(zip(lv, wv)) if x != y]
            r["mismatches"] += len(mm)
            if mm and len(examples) < 5:
                examples.append({"run": path, "defense": d.name, "at": mm, "call": calls[mm[0]]})
    print(json.dumps({"model": a.model, "suite": a.suite, "report": report, "examples": examples}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
