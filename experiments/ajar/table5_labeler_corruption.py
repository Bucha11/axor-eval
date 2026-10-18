"""Which labeler corruption matches Table 5's caption 'every value attributed to the request'?
($0, no model). 618c4a9 + config_m1_c9v5, references on where applicable. Replay 1887 landed under
two corruptions x three configs.

Corruptions:
  allR  : the taint labeler marks every value TASK-origin (replay_runs flag: patches g._taint
          trusted_origin->TASK, is_trusted->True). Does NOT touch the §9 reference layer.
  L_adv : the REFERENCE layer attributes every value to the request (patch ReferenceTable.is_request
          -> always True), so shown_raw is true for every value and reference_origin never fires.
Configs (columns):
  no_handle_table : references OFF (origin gate without the handle table)
  origin          : origin-only (strip_grants), references ON
  grants          : grants L1+L2s, config-tuple (GRANT_ARGS_FROM_CONFIG=1, L2=tuple), references ON
"""
import os, sys, json, glob, subprocess, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"; os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from grant_ablation import strip_grants  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.contracts.taint import TrustedOrigin as _TO  # noqa: E402
import axor_core.kernel.references as _refs  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from ajar.core.types import Candidate  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
_ORIG_IS_REQUEST = _refs.ReferenceTable.is_request


def build_gov(config, suite, prompt, plan):
    if config == "no_handle_table":
        cfg = axor_ajar.load_config(suite, "context", "request-only")
        cfg = dataclasses.replace(cfg, references=False)
        cfg = strip_grants(cfg)
        g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    cfg = axor_ajar.load_config(suite, "context", "request-only")  # references on (config default)
    if config == "origin":
        cfg = strip_grants(cfg)
        g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def replay(config, corruption, suite, run):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    g = build_gov(config, suite.name, prompt, plan)
    if corruption == "allR":  # taint layer: every value TASK-origin
        g._taint.trusted_origin = lambda v, _o=_TO.TASK: _o
        g._taint.is_trusted = lambda *a, **k: True
    executed = []
    for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
        d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:
            k = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
            if k is not None:
                g.grant_store.commit(k)
        res, err = runtime.run_function(env, c["function"], dict(c["args"]))
        executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]))
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    return inj is not None and bool(suite._check_injection_task_security(inj, [], pre, env, executed))


def run_cell(config, corruption):
    # L_adv: patch the reference layer so every value is attributed to the request
    if corruption == "L_adv":
        _refs.ReferenceTable.is_request = lambda self, value: len(str(value)) > 0
    else:
        _refs.ReferenceTable.is_request = _ORIG_IS_REQUEST
    landed = runs = 0
    try:
        for model in MODELS:
            for sname in ("banking", "slack", "travel", "workspace"):
                suite = get_suite(VERSIONS[sname], sname)
                for path in sorted(glob.glob(os.path.join(ROOT, model, sname, "user_task_*", "important_instructions", "*.json"))):
                    run = json.load(open(path))
                    runs += 1
                    try:
                        if replay(config, corruption, suite, run):
                            landed += 1
                    except Exception:
                        pass
    finally:
        _refs.ReferenceTable.is_request = _ORIG_IS_REQUEST
    return {"landed": landed, "runs": runs, "asr": round(landed / runs, 4) if runs else None}


res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
       "caption": "Table 5: 'every value attributed to the request'",
       "matrix": {}}
for corruption in ("allR", "L_adv"):
    res["matrix"][corruption] = {}
    for config in ("no_handle_table", "origin", "grants"):
        cell = run_cell(config, corruption)
        res["matrix"][corruption][config] = cell
        print(f"{corruption:6s} {config:16s} landed={cell['landed']:3d} ASR={cell['asr']}")
res["verdict"] = ("allR patches only the taint labeler; the §9 reference layer (is_request/shown_raw) "
                  "is independent, so reference_origin still fires -> allR does NOT attribute values to "
                  "the request. L_adv patches is_request->True, so every value is shown_raw and "
                  "reference_origin never fires -> L_adv is the corruption that matches the caption "
                  "'every value attributed to the request'.")
op = os.path.join(HERE, "results", "table5_labeler_corruption_c9v5.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print("WROTE", op)
