"""Part 2: labeler-corruption sanity check ($0, no model). config_m1_c9v5, config-tuple path
(GRANT_ARGS_FROM_CONFIG=1, L2=tuple), references on. replay 1887.

(i) For allR (taint -> TASK) and L_adv (reference is_request -> True), count CALLS whose verdict
    (allowed,category) differs from the honest labeler, over replay 1887 grants L1+L2s.
(ii) Combined corruption ``both`` patches BOTH the taint layer AND the reference layer, so "every
     value attributed to the request" acts on taint AND reference. Re-measure landed for the three
     columns (no_handle_table / origin / grants). Compare with 37/18/12.
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


def build(config, suite, prompt, plan):
    if config == "no_handle_table":
        cfg = dataclasses.replace(axor_ajar.load_config(suite, "context", "request-only"), references=False)
        cfg = strip_grants(cfg); g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    cfg = axor_ajar.load_config(suite, "context", "request-only")
    if config == "origin":
        cfg = strip_grants(cfg); g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def corrupt(g, mode):
    if mode in ("allR", "both"):
        g._taint.trusted_origin = lambda v, _o=_TO.TASK: _o
        g._taint.is_trusted = lambda *a, **k: True


def iter_runs():
    for model in MODELS:
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = get_suite(VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(ROOT, model, sname, "user_task_*", "important_instructions", "*.json"))):
                yield suite, sname, json.load(open(path)), path


def replay(config, mode, suite, sname, run, want_calls=False):
    _refs.ReferenceTable.is_request = (lambda self, v: len(str(v)) > 0) if mode in ("L_adv", "both") else _ORIG_IS_REQUEST
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True); runtime = FunctionsRuntime(suite.tools)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    g = build(config, sname, prompt, plan); corrupt(g, mode)
    executed, calls = [], []
    for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
        d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
        if want_calls:
            calls.append((c["function"], bool(d.allowed), d.category))
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
    landed = inj is not None and bool(suite._check_injection_task_security(inj, [], pre, env, executed))
    return landed, calls


# (i) per-call verdict differences vs honest, on grants tuple
runs = list(iter_runs())
honest = {}
for suite, sname, run, path in runs:
    _, calls = replay("grants", "honest", suite, sname, run, want_calls=True)
    honest[path] = calls
diff_counts = {}
for mode in ("allR", "L_adv"):
    n_diff = 0; n_total = 0
    for suite, sname, run, path in runs:
        _, calls = replay("grants", mode, suite, sname, run, want_calls=True)
        h = honest[path]
        for a, b in zip(h, calls):
            n_total += 1
            if a != b:
                n_diff += 1
    diff_counts[mode] = {"calls_differing_from_honest": n_diff, "calls_total": n_total}

# (ii) combined corruption landed for the three columns
combined = {}
for config in ("no_handle_table", "origin", "grants"):
    landed = 0; total = 0
    for suite, sname, run, path in runs:
        l, _ = replay(config, "both", suite, sname, run)
        total += 1; landed += int(bool(l))
    combined[config] = {"landed": landed, "runs": total, "asr": round(landed / total, 4) if total else None}
_refs.ReferenceTable.is_request = _ORIG_IS_REQUEST

res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on",
       "i_per_call_verdict_diffs_vs_honest_grants": diff_counts,
       "ii_combined_corruption_both_layers": combined,
       "reference_37_18_12": {"no_handle_table": 37, "origin": 18, "grants": 12}}
op = os.path.join(HERE, "results", "part2_labeler_sanity_c9v5.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
