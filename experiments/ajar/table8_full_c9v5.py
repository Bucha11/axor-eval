"""Table 8 full re-run, kernel 618c4a9 + config_m1_c9v5, config-grant path
(AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1, AXOR_AJAR_L2=tuple). Three rows:
  origin        = no grants (strip_grants, no template)
  L1+L2 +US133  = grants L1+L2 tuple, US133 added to banking recipient operator_set
  L1+L2         = grants L1+L2 tuple, plain c9v5
For each: (A) paper_opl OPL [95% CI, 2000 boot], sufficiency, attacks/144 over banking Ajar
probes; (B) replay ASR over the 432 banking traces of the 1887 corpus. Plus (C) the 392
ATTACKER_SEEDED probes to US133 under the +US133 row: how many DENY and by which gate.
NO model calls."""
import os, sys, json, glob, dataclasses, subprocess
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"
os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
import run_ajar  # noqa: E402
import paper_opl as P  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from ajar.runner import run_defense  # noqa: E402
from ajar.core.types import Verdict  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
US133 = "US133000000121212121212"
_orig_load = axor_ajar.load_config
ADD = {"on": False}


def _pl(s, i, io):
    c = _orig_load(s, i, io)
    if ADD["on"] and s == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    return c


axor_ajar.load_config = _pl

# ---------- (A) paper_opl metrics over banking probes ----------
data = run_ajar.load(None)
bank_probes = [(s, p) for s, p in data if s.task.suite == "banking"]


def opl_row(defense):
    m = P.measure(defense, bank_probes)
    return {"opl": round(m["opl"]["earliest"], 4), "opl_ci95": m["ci95"]["opl"],
            "sufficiency": m["sufficiency"], "attacks": m["attacks"], "provisioned": m["provisioned"]}


def grants_def():
    return P.make("grants:L1+L2s:R0")  # config path via env; L2 tuple


def origin_def():
    return axor_ajar.AxorDefense("origin", integrity_default="context",
                                 integrity_origins="request-only", no_grants=True)


# ---------- (B) replay ASR over 432 banking traces ----------
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITE = get_suite(VERSIONS["banking"], "banking")


def build_gov(kind, prompt, plan):
    cfg = axor_ajar.load_config("banking", "context", "request-only")
    if kind == "origin":
        cfg = axor_ajar.strip_grants(cfg)
        g = ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(prompt); return g
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite="banking"), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def replay_asr(kind):
    landed = runs = 0
    from ajar.core.types import Candidate
    for model in MODELS:
        for p in sorted(glob.glob(os.path.join(ROOT, model, "banking", "user_task_*", "important_instructions", "*.json"))):
            run = json.load(open(p))
            ut = SUITE.user_tasks[run["user_task_id"]]
            prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
            if isinstance(prompt, list):
                prompt = "".join(b.get("content", "") for b in prompt)
            env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
            pre = env.model_copy(deep=True)
            runtime = FunctionsRuntime(SUITE.tools)
            plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
            g = build_gov(kind, prompt, plan)
            executed = []
            for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
                d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
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
            inj = SUITE.injection_tasks.get(run.get("injection_task_id") or "")
            runs += 1
            if inj is not None and bool(SUITE._check_injection_task_security(inj, [], pre, env, executed)):
                landed += 1
    return {"landed": landed, "runs": runs, "asr": round(landed / runs, 4) if runs else None}


res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
       "grant_path": "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 + AXOR_AJAR_L2=tuple", "rows": {}}

# origin
ADD["on"] = False
res["rows"]["origin (no template)"] = {"opl": opl_row(origin_def()), "replay": replay_asr("origin")}
# L1+L2 without
ADD["on"] = False
res["rows"]["L1+L2 (without US133)"] = {"opl": opl_row(grants_def()), "replay": replay_asr("grants")}
# L1+L2 with US133
ADD["on"] = True
res["rows"]["L1+L2 (US133 in banking O)"] = {"opl": opl_row(grants_def()), "replay": replay_asr("grants")}

# ---------- (C) 392 ATTACKER_SEEDED probes to US133: gate breakdown (under +US133 grants) ----------
from collections import Counter
ADD["on"] = True
import ajar.adapters.agentdojo.adapter as _adp  # noqa: F401
from ajar.adapters.base import get_benchmark
AD = get_benchmark("agentdojo")
cat = Counter(); allow = 0; total = 0
dfn = grants_def()
for s, probes in bank_probes:
    atk = [p for p in probes if getattr(p, "fault_class", None) and p.fault_class.value == "ATTACKER_SEEDED"
           and US133 in str(dict(p.candidate.args))]
    if not atk:
        continue
    spec = AD.task_spec(s.task)
    for pr in atk:
        g = dfn.governor(spec)
        for call, out in axor_ajar.PREFIXES.outputs(spec, pr.context):
            dd = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
            if getattr(dd, "grant_id", None) is not None:
                k = g.spend(dd, axor_ajar.spend_args(dd, dict(call.args)))
                if k is not None:
                    g.grant_store.commit(k)
            if out is not None:
                axor_ajar.present(g, dd, out, call.tool, dict(call.args))
        d = g.evaluate(pr.candidate.tool, axor_ajar.agent_args(g, dict(pr.candidate.args)))
        total += 1
        if d.allowed:
            allow += 1
        else:
            cat[(pr.candidate.tool, d.category)] += 1
res["us133_attacker_probes"] = {"total": total, "allowed": allow, "denied": total - allow,
                                "by_tool_gate": {f"{t}·{c}": n for (t, c), n in cat.most_common()}}
ADD["on"] = False

op = os.path.join(HERE, "results", "table8_full_c9v5.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
