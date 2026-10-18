"""Dump per-call (allowed, category) verdicts for a recorded corpus, to diff OLD vs NEW kernel.
config_m1_c9v5, config-tuple path, references on. No model.  CORPUS env: 'live' | 'replay1887'.
Run once per kernel (KERNEL_WT) and diff the two JSONs: any differing call is a verdict change."""
import os, sys, json, glob, subprocess, dataclasses, re as _re, ast as _ast
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
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from ajar.core.types import Candidate  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
CORPUS = os.environ["CORPUS"]
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]


def parse_tc(tc):
    if isinstance(tc, dict):
        return (tc.get("function") or tc.get("name"), dict(tc.get("args") or tc.get("arguments") or {}), tc.get("id"))
    s = str(tc)
    mf = _re.search(r"function='([^']*)'", s); mi = _re.search(r"id='([^']*)'", s)
    ma = _re.search(r"args=(\{.*\})\s+id=", s)
    args = {}
    if ma:
        try:
            args = _ast.literal_eval(ma.group(1))
        except Exception:
            args = {}
    return (mf.group(1) if mf else None, dict(args) if isinstance(args, dict) else {}, mi.group(1) if mi else None)


def grants_gov(suite, prompt, plan):
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    cfg = axor_ajar.load_config(suite, "context", "request-only")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


out = {"kernel_commit": KERNEL, "corpus": CORPUS, "verdicts": {}}

if CORPUS == "replay1887":
    for model in MODELS:
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = get_suite(VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(ROOT, model, sname, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(path)); ut = suite.user_tasks[run["user_task_id"]]
                prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
                if isinstance(prompt, list):
                    prompt = "".join(b.get("content", "") for b in prompt)
                env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
                pre = env.model_copy(deep=True); runtime = FunctionsRuntime(suite.tools)
                plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
                g = grants_gov(sname, prompt, plan)
                key = os.path.relpath(path, ROOT); seq = []
                for i, c in enumerate([tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]):
                    d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
                    seq.append([c["function"], bool(d.allowed), d.category])
                    if not d.allowed:
                        continue
                    if getattr(d, "grant_id", None) is not None:
                        k = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
                        if k is not None:
                            g.grant_store.commit(k)
                    res, err = runtime.run_function(env, c["function"], dict(c["args"]))
                    if err is None:
                        axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]))
                out["verdicts"][key] = seq

elif CORPUS == "live":
    for mode in ("A", "B", "origin-only"):
        base = os.path.join(HERE, "results", "live_c9v5", mode) if mode in ("A", "B") else \
            os.path.join(HERE, "results", "live_origin_c9v5_v2")
        for p in sorted(glob.glob(os.path.join(base, "pass*", "traj", "*", "user_task_*.json"))):
            d = json.load(open(p)); suite = d["suite"]
            msgs = d.get("messages") or []
            prompt = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            if isinstance(prompt, list):
                prompt = "".join(b.get("content", "") for b in prompt)
            results = {}
            for m in msgs:
                if m.get("role") == "tool":
                    c = m.get("content")
                    txt = "".join(b.get("content", "") for b in c) if isinstance(c, list) else str(c)
                    results[m.get("tool_call_id")] = (txt, m.get("error"))
            if mode == "origin-only":
                cfg = strip_grants(axor_ajar.load_config(suite, "context", "request-only"))
                g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt)
            else:
                lv = "L1" if mode == "A" else "L1+L4"; cf = "oracle" if mode == "A" else "view"
                kwargs, hook = axor_ajar.grants_kwargs(lv, confirm=cf)
                cfg = axor_ajar.load_config(suite, "context", "request-only")
                spec = SimpleNamespace(task=SimpleNamespace(suite=suite), prompt=prompt, plan=[])
                kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
                g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)
            key = os.path.relpath(p, os.path.join(HERE, "results")); seq = []
            for m in msgs:
                if m.get("role") != "assistant":
                    continue
                for tc in (m.get("tool_calls") or []):
                    tool, args, tcid = parse_tc(tc)
                    if not tool:
                        continue
                    d = g.evaluate(tool, axor_ajar.agent_args(g, args))
                    seq.append([tool, bool(d.allowed), d.category])
                    if d.allowed:
                        if getattr(d, "grant_id", None) is not None:
                            k = g.spend(d, axor_ajar.spend_args(d, args))
                            if k is not None:
                                g.grant_store.commit(k)
                        o = results.get(tcid)
                        if o and o[1] is None:
                            axor_ajar.present(g, d, o[0], tool, args)
            out["verdicts"][key] = seq

op = os.path.join("/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad", f"verdicts_{CORPUS}_{KERNEL}.json")
json.dump(out, open(op, "w"))
print("calls:", sum(len(v) for v in out["verdicts"].values()), "traces:", len(out["verdicts"]), "WROTE", op)
