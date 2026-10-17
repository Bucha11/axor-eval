"""Per-episode replay of the 432 banking traces (1887 corpus) under two origin-no-grants
configs that differ ONLY in the handle table (references): refs_on__L_std vs refs_off__L_std
(as in replay_refs_labeler.py). NO model calls. c9v5 configs, kernel 618c4a9.

For each episode we record, under each config, the governor's per-call decisions (tool, the
destination value, allowed, category, grant_source, description) and the injection security
outcome. We then emit every episode whose landed outcome differs between the two configs,
with the decisive call(s) whose verdict flipped. Writes results/handle_table_banking_c9v5.json.
"""
import os, sys, json, glob, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ.pop("AXOR_HYP", None)
sys.path.insert(0, WT)
sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")   # grant_ablation for axor_ajar import
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
ATTACK = "important_instructions"
CELLS = {"refs_on__L_std": True, "refs_off__L_std": False}   # references flag


def strip_grants(cfg):
    return dataclasses.replace(
        cfg, grant_args={}, grant_templates={}, grant_quotas={}, description_sources={},
        description_targets={}, delegated_sources={}, list_union=False, list_args={},
        max_unattended_consequence=ConsequenceClass.CONSEQUENTIAL)


def make_governor(suite_name, prompt, references):
    cfg = axor_ajar.load_config(suite_name, "context", "request-only")
    cfg = dataclasses.replace(cfg, references=references)
    cfg = strip_grants(cfg)
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    return g   # L_std: no labeler patch


def dest_value(tool, args):
    for k in ("recipient", "iban", "to", "address"):
        if k in args:
            return args[k]
    return {k: args[k] for k in list(args)[:2]}


def replay(suite, run, references):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    g = make_governor(suite.name, prompt, references)
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    executed, log = [], []
    for c in calls:
        aargs = axor_ajar.agent_args(g, dict(c["args"]))
        d = g.evaluate(c["function"], aargs)
        log.append({"tool": c["function"], "value": dest_value(c["function"], dict(c["args"])),
                    "allowed": bool(d.allowed), "category": d.category,
                    "grant_source": getattr(d, "grant_source", None),
                    "description": getattr(d, "description", None)})
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
            if key is not None:
                g.grant_store.commit(key)
        res, err = runtime.run_function(env, c["function"], dict(c["args"]))
        executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]))
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    sec = bool(suite._check_injection_task_security(inj, [], pre, env, executed)) if inj is not None else None
    return sec, log


root = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
suite = get_suite(VERSIONS["banking"], "banking")
episodes, diffs = [], []
tally = {"refs_on__L_std": 0, "refs_off__L_std": 0}
for model in MODELS:
    for path in sorted(glob.glob(os.path.join(root, model, "banking", "user_task_*", ATTACK, "*.json"))):
        run = json.load(open(path))
        sec_on, log_on = replay(suite, run, True)
        sec_off, log_off = replay(suite, run, False)
        tally["refs_on__L_std"] += int(bool(sec_on))
        tally["refs_off__L_std"] += int(bool(sec_off))
        rec = {"model": model, "user_task": run["user_task_id"], "injection": run.get("injection_task_id"),
               "landed_refs_on": bool(sec_on), "landed_refs_off": bool(sec_off)}
        episodes.append(rec)
        if bool(sec_on) != bool(sec_off):
            # decisive flipped calls: same position, allowed differs
            flips = []
            for i, (a, b) in enumerate(zip(log_on, log_off)):
                if a["allowed"] != b["allowed"]:
                    flips.append({"i": i, "tool": a["tool"], "value": a["value"],
                                  "refs_on": {"allowed": a["allowed"], "category": a["category"],
                                              "grant_source": a["grant_source"], "description": a["description"]},
                                  "refs_off": {"allowed": b["allowed"], "category": b["category"],
                                               "grant_source": b["grant_source"], "description": b["description"]}})
            diffs.append({**rec, "flipped_calls": flips})

out = {"task": "banking_handle_table", "corpus_runs": len(episodes), "models": MODELS,
       "kernel_commit": "618c4a9", "config_dir": "config_m1_c9v5",
       "mode": "origin-no-grants = strip_grants (ceiling CONSEQUENTIAL), L_std",
       "cells_differ_only_in": "references (handle table)",
       "landed_tally": tally, "diff_count": len(diffs), "diffs": diffs, "episodes": episodes}
op = os.path.join(HERE, "results", "handle_table_banking_c9v5.json")
json.dump(out, open(op, "w"), indent=1)
print("banking runs:", len(episodes), " landed tally:", tally, " diffs:", len(diffs))
for d in diffs:
    print(f"\n{d['model']} {d['user_task']} inj={d['injection']} on={d['landed_refs_on']} off={d['landed_refs_off']}")
    for f in d["flipped_calls"]:
        print(f"   call[{f['i']}] {f['tool']}({f['value']!r}): "
              f"on={f['refs_on']['allowed']}/{f['refs_on']['category']}/gs={f['refs_on']['grant_source']}/desc={f['refs_on']['description']!r}  "
              f"off={f['refs_off']['allowed']}/{f['refs_off']['category']}/gs={f['refs_off']['grant_source']}")
print("\nWROTE", op)
