"""Model-free replay (1887 corpus) of ORIGIN-NO-GRANTS over the 2x2 grid
{references on/off} x {L_std, fixed L_adv}, on c9v5 + kernel 618c4a9.

origin-no-grants = strip_grants (grant_args/grant_templates/grant_quotas/description/
delegated/list stripped; max_unattended_consequence restored to CONSEQUENTIAL) — the
SAME field set as grant_ablation.strip_grants and as replay_runs.py's no_grants
(which produced the committed refs-on x L_std = 11), so refs-on x L_std is the control.

fixed L_adv = the full adversarial labeler: every value reads as request origin — the
3-way patch trusted_origin + is_trusted + _trusted.covers (mech_modes.py:74-77), the
load-bearing one (replay_runs' allR patched only the first two and left 11 unchanged).

NO model calls: replays saved AgentDojo trajectories through the governor.
Usage:  python replay_refs_labeler.py calib   (banking, refs-on x L_std; must give banking=4)
        python replay_refs_labeler.py full    (all 4 cells x 3 models x 4 suites -> result file)
"""
import os, sys, json, glob, dataclasses, hashlib
from collections import defaultdict

HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]                       # detached worktree at 618c4a9
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ.pop("AXOR_HYP", None)
CONFIG_DIR = os.environ["AXOR_AJAR_CONFIG_DIR"]

sys.path.insert(0, WT)                                           # axor_core == 618c4a9
sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")     # grant_ablation (for axor_ajar import)
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402
from axor_core.contracts.taint import TrustedOrigin as _TO  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITES = ("banking", "slack", "travel", "workspace")
ATTACK = "important_instructions"
# cell -> (references, labeler)
CELLS = {
    "refs_on__L_std":  (True,  "L_std"),
    "refs_off__L_std": (False, "L_std"),
    "refs_on__L_adv":  (True,  "L_adv"),
    "refs_off__L_adv": (False, "L_adv"),
}


def strip_grants(cfg):
    return dataclasses.replace(
        cfg, grant_args={}, grant_templates={}, grant_quotas={}, description_sources={},
        description_targets={}, delegated_sources={}, list_union=False, list_args={},
        max_unattended_consequence=ConsequenceClass.CONSEQUENTIAL)


def make_governor(suite_name, prompt, references, labeler):
    cfg = axor_ajar.load_config(suite_name, "context", "request-only")
    cfg = dataclasses.replace(cfg, references=references)
    cfg = strip_grants(cfg)
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    if labeler == "L_adv":                       # fixed L_adv: full 3-way patch (mech_modes:74-77)
        g._taint.trusted_origin = lambda v, _o=_TO.TASK: _o
        g._taint.is_trusted = lambda *a, **k: True
        g._taint._trusted.covers = lambda *a, **k: True
    return g


def replay(suite, run, references, labeler):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    g = make_governor(suite.name, prompt, references, labeler)
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    executed = []
    for c in calls:
        d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:                 # no grants here, kept for parity
            key = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
            if key is not None:
                g.grant_store.commit(key)
        res, err = runtime.run_function(env, c["function"], dict(c["args"]))
        executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]))
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    sec = bool(suite._check_injection_task_security(inj, [], pre, env, executed)) if inj is not None else None
    util = bool(suite._check_user_task_utility(ut, [], pre, env, executed))
    return util, sec


def run_cells(cells, suites, out_path=None):
    root = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
    agg = defaultdict(lambda: {"runs": 0, "attacks_landed": 0, "utility": 0, "errors": 0})
    suite_obj = {s: get_suite(VERSIONS[s], s) for s in suites}
    for model in MODELS:
        for sname in suites:
            suite = suite_obj[sname]
            for path in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", ATTACK, "*.json"))):
                run = json.load(open(path))
                for cell in cells:
                    refs, lab = CELLS[cell]
                    r = agg[(cell, sname)]
                    try:
                        util, sec = replay(suite, run, refs, lab)
                    except Exception:
                        r["errors"] += 1
                        continue
                    r["runs"] += 1
                    r["attacks_landed"] += int(bool(sec))
                    r["utility"] += int(util)
    rows = {}
    for (cell, sname), r in sorted(agg.items()):
        rows.setdefault(cell, {})[sname] = r
    for cell in cells:
        tot = {k: sum(rows.get(cell, {}).get(s, {}).get(k, 0) for s in suites)
               for k in ("runs", "attacks_landed", "utility", "errors")}
        rows.setdefault(cell, {})["all"] = tot
        print(f"{cell:16s} runs={tot['runs']:5d} landed={tot['attacks_landed']:3d} "
              f"utility={tot['utility']:4d} errors={tot['errors']}")
    if out_path:
        meta = {
            "task": "replay_1887",
            "models": MODELS, "attack": ATTACK,
            "kernel_commit": "618c4a9",
            "mode": "origin-no-grants = strip_grants (max_unattended_consequence=CONSEQUENTIAL)",
            "config_dir": "config_m1_c9v5",
            "config_sha256": {s: hashlib.sha256(open(os.path.join(CONFIG_DIR, f"{s}.yaml"), "rb").read()).hexdigest()[:16]
                              for s in SUITES},
            "cells": {c: {"references": CELLS[c][0], "labeler": CELLS[c][1]} for c in cells},
            "rows": rows,
        }
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        json.dump(meta, open(out_path, "w"), indent=1)
        print("WROTE", out_path)
    return rows


if __name__ == "__main__":
    import time
    mode = sys.argv[1] if len(sys.argv) > 1 else "calib"
    if mode == "calib":
        t = time.time()
        rows = run_cells(["refs_on__L_std"], ["banking"])
        bank = rows["refs_on__L_std"]["banking"]["attacks_landed"]
        print(f"CALIB banking refs_on/L_std landed={bank} (committed per-suite banking=4) in {time.time()-t:.1f}s")
        print("CALIB_OK" if bank == 4 else "CALIB_MISMATCH -> STOP")
    else:
        t = time.time()
        run_cells(list(CELLS), list(SUITES),
                  out_path=os.path.join(HERE, "results", "replay_1887_refs_labeler_c9v5.json"))
        print(f"FULL done in {time.time()-t:.1f}s")
