"""Re-decide the recorded live STRICT trajectories (gpt-4o-mini) under config_rule.

    AXOR_CORE_REPO=<kernel> python replay_strict_live.py <records.jsonl ...> <out.json>

Each governed record (run_agentdojo.py AXOR_BENCH_RECORD, calls[] = every decision of
the episode) is rebuilt in AgentDojo: the same injections (the attack named in the run,
addressed to the same model token), then the recorded calls in order. A call STRICT
allowed is executed with its executed args and its real output is registered with the
config_rule governor; a call STRICT refused was not executed and is only evaluated.
Every call gets the config_rule verdict, with and without L1+L2s grants (R0 args), the
governor built as the Ajar wrapper builds it (context integrity, request-only).
"""
from __future__ import annotations

import collections
import dataclasses
import json
import os
import sys

CORE = os.environ["AXOR_CORE_REPO"]
sys.path.insert(0, CORE)
sys.path.append(os.environ.get("AXOR_ATTACKS_DIR", "/home/user/axor-core/examples/agentdojo"))  # adaptive_attacks.py
HERE = os.path.dirname(os.path.abspath(__file__))

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

CONFIG_DIR = os.environ.get("AXOR_AJAR_CONFIG_DIR") or os.path.join(HERE, "config_rule")
R0 = json.load(open(os.path.join(HERE, "live", "grant_args_R0.json")))
TPL = json.load(open(os.path.join(HERE, "live", "templates_L2s.json")))
MODEL_TOKEN = "gpt-4o-2024-05-13"  # run_agentdojo's token for gpt-4o* models


def governor(suite, prompt, grants):
    cfg = GovernanceConfig.from_yaml(os.path.join(CONFIG_DIR, f"{suite}.yaml"))
    cfg = dataclasses.replace(cfg, integrity_default="context", integrity_origins="request-only")
    kw = cfg.as_governor_kwargs()
    if grants:
        kw["grant_args"] = R0.get(suite, {})
        if TPL.get(suite):
            kw["grant_templates"] = TPL[suite]
    g = ToolCallGovernor(**kw)
    g.register_task(prompt)
    if grants:
        g.grants.from_request(prompt)
    return g


class _P:  # the attack only reads the pipeline's name
    name = f"axor-governed-{MODEL_TOKEN}"


def main(paths, out):
    from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite
    import adaptive_attacks  # noqa: F401  (registers axor_adaptive)

    res = []
    suites, attacks = {}, {}
    for path in paths:
        attack_name = "axor_adaptive" if "adaptive" in path else "important_instructions"
        for line in open(path):
            r = json.loads(line)
            if r["condition"] != "governed" or r["calls"] is None or r["error"]:
                continue
            s = r["suite"]
            if s not in suites:
                suites[s] = get_suite("v1", s)
            suite = suites[s]
            ut = suite.get_user_task_by_id(r["user_task"])
            if r["injection_task"]:
                key = (s, attack_name)
                if key not in attacks:
                    attacks[key] = load_attack(attack_name, suite, _P())
                inj = attacks[key].attack(ut, suite.get_injection_task_by_id(r["injection_task"]))
            else:
                inj = {}
            env = suite.load_and_inject_default_environment(inj)
            runtime = FunctionsRuntime(suite.tools)
            gs = {"a": governor(s, ut.PROMPT, False), "b": governor(s, ut.PROMPT, True)}
            calls = []
            for c in r["calls"]:
                args = dict(c["proposed"] or {})
                row = {"tool": c["tool"], "strict_allowed": c["allowed"], "strict_category": c["category"]}
                decs = {}
                for k, g in gs.items():
                    d = g.evaluate(c["tool"], dict(args))
                    decs[k] = d
                    row[f"rule_{k}"] = bool(d.allowed)
                    row[f"rule_{k}_category"] = d.category
                    if not d.allowed:
                        row[f"rule_{k}_reason"] = (d.reason or "")[:160]
                if c["allowed"]:
                    out_v, err = runtime.run_function(env, c["tool"], dict(c["executed"] or args))
                    text = tool_result_to_str(out_v) if err is None else str(err)
                    for k, g in gs.items():
                        d = decs[k]
                        if d.allowed and getattr(d, "grant_id", None) is not None:
                            kk = g.spend(d, dict(args))
                            if kk is not None:
                                g.grant_store.commit(kk)
                        try:
                            g.register_output(d, text)
                        except Exception:
                            pass
                calls.append(row)
            res.append({k: r[k] for k in ("suite", "axis", "user_task", "injection_task", "pass", "utility", "security")}
                       | {"attack": attack_name if r["injection_task"] else None, "calls": calls})
    json.dump(res, open(out, "w"), indent=1, default=str)
    print(out, len(res), "episodes", sum(len(x["calls"]) for x in res), "calls")


if __name__ == "__main__":
    main(sys.argv[1:-1], sys.argv[-1])
