"""Value-equality collisions on AgentDojo, offline.

Proposition 2 clears a driving value at an integrity or egress sink when it EQUALS
a registered trusted value (the request, operator configuration, and under
any-trusted a declared benign tool's output). An attacker value that merely
coincides with such a value would clear. This counts, per suite, the driving
values of every injection task's ground-truth sink calls (the attacker's intended
effect) that equal

  * a value the user's request names (TASK) — any user task of the suite;
  * a value anywhere in the suite's default environment (an over-approximation of
    what benign reads can return under any-trusted).

Driving arguments are the ones the suites' origin configurations declare.

Run: AXOR_CORE=../axor-core uv run --no-project --with agentdojo==0.1.35 \
  --with pyyaml python experiments/review_offline/collisions.py
"""
from __future__ import annotations

import os

import yaml

SUITES = ("banking", "slack", "travel", "workspace")
CFG = {"banking": "banking_origin.yaml", "slack": "slack_origin.yaml",
       "travel": "travel_origin.yaml", "workspace": "workspace.yaml"}


def _leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _leaves(v)
    elif isinstance(x, (list, tuple, set)):
        for v in x:
            yield from _leaves(v)
    elif isinstance(x, (str, int, float)) and not isinstance(x, bool):
        yield x


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else float(v)


def analyse():
    from agentdojo.task_suite.load_suites import get_suite
    core = os.environ.get("AXOR_CORE", "../axor-core")
    out = {}
    for name in SUITES:
        suite = get_suite("v1", name)
        cfg = yaml.safe_load(open(os.path.join(core, "examples/agentdojo/config", CFG[name])))
        driving = cfg.get("driving_args", {})
        env = suite.load_and_inject_default_environment({})
        env_vals = {_norm(v) for v in _leaves(env.model_dump())}
        prompts = [ut.PROMPT.lower() for ut in suite.user_tasks.values()]
        n_pairs = len(prompts) * len(suite.injection_tasks)
        pairs_task, pairs_env, examples = 0, 0, []
        for it in suite.injection_tasks.values():
            vals = [v for call in it.ground_truth(env)
                    for arg in driving.get(call.function, []) if arg in call.args
                    for v in _leaves(call.args[arg])]
            env_hit = [v for v in vals if _norm(v) in env_vals]
            task_hits = sum(any(isinstance(v, str) and v.lower() in p for v in vals) for p in prompts)
            pairs_task += task_hits
            pairs_env += len(prompts) if env_hit else 0
            if env_hit or task_hits:
                examples.append((type(it).__name__, sorted(set(map(str, vals))),
                                 f"env:{bool(env_hit)}", f"prompts:{task_hits}"))
        out[name] = {"pairs": n_pairs, "pairs_cleared_by_request": pairs_task,
                     "pairs_cleared_by_environment_value": pairs_env, "examples": examples}
    return out


if __name__ == "__main__":  # pragma: no cover
    for k, v in analyse().items():
        print(k, {x: y for x, y in v.items() if x != "examples"})
        for e in v["examples"]:
            print("   ", e)
