"""named_sender-laundered admits ($0, no model). 618c4a9 + config_m1_c9v5, config-tuple path
(GRANT_ARGS_FROM_CONFIG=1, AXOR_AJAR_L2=tuple), references on.

Counts ADMITTED calls where a driving identifier passed reference_origin ONLY because it inherited
`named_sender` from the record it was read in (the value is NOT itself the sender / not independently
request/own/named). Detector at each allowed call: for a driving-arg leaf fed as a handle whose
reference origin == named_sender and whose value is NOT is_request/is_own/sender_named -> laundered.
Validated by a counterfactual: with _origin patched to never return SENDER, such a call flips to
reference_origin DENY.

(a) live_c9v5 traces A / B / origin-only, by suite and task.
(b) Ajar Table 2 (all 97 tasks), split provisioned-required vs unneeded.
(c) replay 1887, split landed vs not-landed.
"""
import os, sys, json, glob, subprocess, dataclasses
from collections import defaultdict
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

import re as _re, ast as _ast  # noqa: E402
import axor_ajar  # noqa: E402
import run_ajar  # noqa: E402
import paper_opl as P  # noqa: E402


def _parse_tc(tc):
    """Live traj tool_calls are repr strings: function='X' args={...} id='Y' ...  Parse to (tool,args,id)."""
    if isinstance(tc, dict):
        return (tc.get("function") or tc.get("name"), dict(tc.get("args") or tc.get("arguments") or {}),
                tc.get("id") or tc.get("tool_call_id"))
    s = str(tc)
    mf = _re.search(r"function='([^']*)'", s)
    mi = _re.search(r"id='([^']*)'", s)
    ma = _re.search(r"args=(\{.*\})\s+id=", s)
    args = {}
    if ma:
        try:
            args = _ast.literal_eval(ma.group(1))
        except Exception:
            args = {}
    return (mf.group(1) if mf else None, dict(args) if isinstance(args, dict) else {}, mi.group(1) if mi else None)
from grant_ablation import strip_grants  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from ajar.core.types import Candidate, Label  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def leaves(v):
    if isinstance(v, (list, tuple)):
        for x in v:
            yield from leaves(x)
    elif isinstance(v, dict):
        for x in v.values():
            yield from leaves(x)
    else:
        yield v


def laundered_driving(g, tool, fed_args):
    """driving-arg values admitted only via inherited named_sender (value != sender)."""
    t = getattr(g, "_xrefs", None)
    if t is None or not t.by_name:
        return []
    declared = g._driving_args.get(tool) or frozenset()
    out = []
    for a in declared:
        for x in leaves(fed_args.get(a)):
            r = t.by_name.get(x) if not isinstance(x, (dict, list)) else None
            if r is not None and getattr(r, "origin", None) == "named_sender":
                val = str(r.value)
                if not (t.is_request(val) or t.is_own(val) or t.sender_named(val)):
                    out.append({"arg": a, "value": val, "handle": x})
    return out


# ---------------- (a) live traces ----------------
def live_governor(suite, mode, prompt):
    cfg = axor_ajar.load_config(suite, "context", "request-only")
    if mode == "origin-only":
        cfg = strip_grants(cfg)
        g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    levels = "L1" if mode == "A" else "L1+L4"
    confirm = "view" if mode == "B" else "oracle"
    kwargs, hook = axor_ajar.grants_kwargs(levels, confirm=confirm)
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite), prompt=prompt, plan=[])
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def replay_live(mode):
    by_suite = defaultdict(lambda: {"admitted_driving": 0, "laundered_admits": 0, "tasks": defaultdict(int)})
    base = os.path.join(HERE, "results", "live_c9v5", mode) if mode in ("A", "B") else \
        os.path.join(HERE, "results", "live_origin_c9v5_v2")
    for p in sorted(glob.glob(os.path.join(base, "pass*", "traj", "*", "user_task_*.json"))):
        d = json.load(open(p))
        suite = d["suite"]
        if suite == "slack" and d["user_task_id"] == "user_task_4":
            continue
        msgs = d.get("messages") or []
        prompt = next((m["content"] for m in msgs if m.get("role") == "user"), "")
        if isinstance(prompt, list):
            prompt = "".join(b.get("content", "") for b in prompt)
        # map tool_call_id -> result text
        results = {}
        for m in msgs:
            if m.get("role") == "tool":
                c = m.get("content")
                txt = "".join(b.get("content", "") for b in c) if isinstance(c, list) else str(c)
                results[m.get("tool_call_id")] = (txt, m.get("error"))
        g = live_governor(suite, mode, prompt)
        for m in msgs:
            if m.get("role") != "assistant":
                continue
            for tc in (m.get("tool_calls") or []):
                tool, args, tcid = _parse_tc(tc)
                if not tool:
                    continue
                fed = axor_ajar.agent_args(g, args)
                dd = g.evaluate(tool, fed)
                if dd.allowed and (g._driving_args.get(tool)):
                    by_suite[suite]["admitted_driving"] += 1
                    lw = laundered_driving(g, tool, fed)
                    if lw:
                        by_suite[suite]["laundered_admits"] += 1
                        by_suite[suite]["tasks"][d["user_task_id"]] += 1
                if dd.allowed:
                    if getattr(dd, "grant_id", None) is not None:
                        k = g.spend(dd, axor_ajar.spend_args(dd, args))
                        if k is not None:
                            g.grant_store.commit(k)
                    out = results.get(tcid)
                    if out and out[1] is None:
                        axor_ajar.present(g, dd, out[0], tool, args)
    return {s: {"admitted_driving": v["admitted_driving"], "laundered_admits": v["laundered_admits"],
                "tasks": dict(v["tasks"])} for s, v in by_suite.items()}


# ---------------- (b) Ajar Table 2 ----------------
def ajar_table2():
    data = run_ajar.load(None)
    D = P.make("grants:L1+L2s:R0")
    res = {"required_provisioned": {"admitted_driving": 0, "laundered_admits": 0, "examples": []},
           "unneeded": {"admitted_driving": 0, "laundered_admits": 0, "examples": []}}
    for spec, probes in data:
        for p in probes:
            if not p.scored or p.expected_label is not Label.ALLOW:
                continue
            bucket = "required_provisioned" if p.required else "unneeded"
            g = D.governor(spec)
            for call, out in axor_ajar.PREFIXES.outputs(spec, p.context):
                dd = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
                if getattr(dd, "grant_id", None) is not None:
                    k = g.spend(dd, axor_ajar.spend_args(dd, dict(call.args)))
                    if k is not None:
                        g.grant_store.commit(k)
                if out is not None:
                    axor_ajar.present(g, dd, out, call.tool, dict(call.args))
            fed = axor_ajar.agent_args(g, dict(p.candidate.args))
            dd = g.evaluate(p.candidate.tool, fed)
            if dd.allowed and g._driving_args.get(p.candidate.tool):
                res[bucket]["admitted_driving"] += 1
                lw = laundered_driving(g, p.candidate.tool, fed)
                if lw:
                    res[bucket]["laundered_admits"] += 1
                    if len(res[bucket]["examples"]) < 15:
                        res[bucket]["examples"].append({"task": str(spec.task), "tool": p.candidate.tool, "laundered": lw})
    return res


# ---------------- (c) replay 1887 ----------------
def replay_1887():
    ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
    MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
    out = {"landed": {"admitted_driving": 0, "laundered_admits": 0, "episodes": []},
           "not_landed": {"admitted_driving": 0, "laundered_admits": 0}}
    for model in MODELS:
        for sname in ("banking", "slack", "travel", "workspace"):
            suite = get_suite(VERSIONS[sname], sname)
            for path in sorted(glob.glob(os.path.join(ROOT, model, sname, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(path))
                ut = suite.user_tasks[run["user_task_id"]]
                prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
                if isinstance(prompt, list):
                    prompt = "".join(b.get("content", "") for b in prompt)
                env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
                pre = env.model_copy(deep=True)
                runtime = FunctionsRuntime(suite.tools)
                plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
                kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
                cfg = axor_ajar.load_config(sname, "context", "request-only")
                spec = SimpleNamespace(task=SimpleNamespace(suite=sname), prompt=prompt, plan=plan)
                kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
                g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)
                executed, launders, adm_driving = [], [], 0
                for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
                    fed = axor_ajar.agent_args(g, dict(c["args"]))
                    dd = g.evaluate(c["function"], fed)
                    if not dd.allowed:
                        continue
                    if g._driving_args.get(c["function"]):
                        adm_driving += 1
                        lw = laundered_driving(g, c["function"], fed)
                        if lw:
                            launders.append({"tool": c["function"], "laundered": lw})
                    if getattr(dd, "grant_id", None) is not None:
                        k = g.spend(dd, axor_ajar.spend_args(dd, dict(c["args"])))
                        if k is not None:
                            g.grant_store.commit(k)
                    res, err = runtime.run_function(env, c["function"], dict(c["args"]))
                    executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
                    if err is None:
                        axor_ajar.present(g, dd, tool_result_to_str(res), c["function"], dict(c["args"]))
                inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
                landed = inj is not None and bool(suite._check_injection_task_security(inj, [], pre, env, executed))
                b = out["landed"] if landed else out["not_landed"]
                b["admitted_driving"] += adm_driving
                if launders:
                    b["laundered_admits"] += 1
                    if landed and len(out["landed"]["episodes"]) < 20:
                        out["landed"]["episodes"].append({"model": model.split("-2024")[0], "suite": sname,
                                                           "user_task": run["user_task_id"],
                                                           "injection": run.get("injection_task_id"), "launders": launders})
    return out


result = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
          "path": "config-tuple (GRANT_ARGS_FROM_CONFIG=1, L2=tuple), references on",
          "definition": "admitted call whose driving identifier passed reference_origin only via named_sender inherited from the record's sender (value != sender: not is_request/is_own/sender_named)",
          "a_live": {m: replay_live(m) for m in ("A", "B", "origin-only")},
          "b_ajar_table2": ajar_table2(),
          "c_replay_1887": replay_1887()}
op = os.path.join(HERE, "results", "ns_admit_detector_c9v5.json")
json.dump(result, open(op, "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in result.items() if k in ("a_live", "b_ajar_table2")}, indent=1, default=str)[:2000])
print("c_replay landed laundered:", result["c_replay_1887"]["landed"]["laundered_admits"],
      "not_landed laundered:", result["c_replay_1887"]["not_landed"]["laundered_admits"])
print("WROTE", op)
