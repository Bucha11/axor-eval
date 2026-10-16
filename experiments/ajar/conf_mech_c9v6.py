"""Confirmer policies on the SAME harness that gave M3=7 (mech_modes path): grants from
config_m1_c9v6 (AXOR_AJAR_GRANT_ARGS_FROM_CONFIG), floor audience, L2=tuple, references on,
counters on, typed senders. Kernel cad07bc (frozen c9v6). No API.

Variants (cumulative over M3 base):
  R0 L1+L2s : M3 base, no confirmer
  oracle    : M3 + L4 oracle confirmer
  view      : M3 + L4 view-aware confirmer
  naive     : M3 + L4 naive confirmer

    AXOR_CORE_REPO=/home/user/core-m1 python conf_mech_c9v6.py results/conf_mech_c9v6.json
"""
import os, sys, glob, json, hashlib, dataclasses, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v6")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"   # grants = config driving args (mech_modes path)
os.environ["AXOR_AJAR_L2"] = "tuple"                   # L2 = kernel tuple templates from value_policies
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.task_suite.load_suites import get_suite
from ajar.core.types import Candidate
from check_wrapper import VERSIONS
from types import SimpleNamespace

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITES = ["banking", "slack", "travel", "workspace"]
VARIANTS = {  # (levels, confirm)
    "R0 L1+L2s": ("L1+L2s", None),
    "oracle":    ("L1+L2s+L4", "oracle"),
    "view":      ("L1+L2s+L4", "view"),
    "naive":     ("L1+L2s+L4", "naive"),
}
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")


def build(levels, confirm, suite, prompt, plan):
    # mirrors mech_modes.build M3 (refs on, tuple on, counters on), plus the L4 layer
    cfg = axor_ajar.load_config(suite.name, "context", "request-only")
    cfg = dataclasses.replace(cfg, references=True)
    kwargs, hook = axor_ajar.grants_kwargs(levels, tuple_grants=True, counters=True,
                                           confirm=confirm or "oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite.name), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)  # L_std: no labeler patch
    return g


def replay(levels, confirm, suite, run):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True); rt = FunctionsRuntime(suite.tools)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    g = build(levels, confirm, suite, prompt, plan); executed = []
    for c in calls:
        d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
            if key is not None:
                g.grant_store.commit(key)
        res, err = rt.run_function(env, c["function"], dict(c["args"]))
        executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]), typed=res)
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    sec = bool(suite._check_injection_task_security(inj, [], pre, env, executed)) if inj is not None else False
    util = bool(suite._check_user_task_utility(ut, [], pre, env, executed))
    return sec, util


agg = {k: {"runs": 0, "landed": 0, "utility": 0, "errors": 0} for k in VARIANTS}
for m in MODELS:
    for s in SUITES:
        suite = get_suite(VERSIONS[s], s)
        for p in sorted(glob.glob(os.path.join(ROOT, m, s, "user_task_*", "important_instructions", "*.json"))):
            run = json.load(open(p))
            for name, (lv, cf) in VARIANTS.items():
                r = agg[name]
                try:
                    sec, util = replay(lv, cf, suite, run)
                except Exception:
                    r["errors"] += 1; continue
                r["runs"] += 1; r["landed"] += int(sec); r["utility"] += int(util)

hashes = {f: hashlib.sha256(open(os.path.join(HERE, "config_m1_c9v6", f), "rb").read()).hexdigest()[:16]
          for f in ["banking.yaml", "slack.yaml", "travel.yaml", "workspace.yaml"]}
khead = subprocess.run(["git", "-C", CORE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
out = {"harness": "mech_modes path (config grant_args, L2=tuple, floor audience, references, counters, typed senders)",
       "config_dir": "config_m1_c9v6", "config_sha256_16": hashes, "kernel_head": khead,
       "env": {"AXOR_AJAR_GRANT_ARGS_FROM_CONFIG": "1", "AXOR_AJAR_L2": "tuple"}, "variants": {}}
for name, r in agg.items():
    n = r["runs"] or 1
    out["variants"][name] = {"runs": r["runs"], "landed": r["landed"], "ASR": round(r["landed"] / n, 4),
                             "utility": round(r["utility"] / n, 4), "errors": r["errors"]}
dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results", "conf_mech_c9v6.json")
json.dump(out, open(dest, "w"), indent=1)
print(json.dumps(out, indent=1)); print("DONE", dest)
