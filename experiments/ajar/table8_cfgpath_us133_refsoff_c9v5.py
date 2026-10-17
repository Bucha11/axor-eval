"""Table 8 single row, kernel 618c4a9 + config_m1_c9v5, CONFIG-grant path
(AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1, AXOR_AJAR_L2=tuple), US133 added to the banking
recipient operator_set, references=false. Outputs: OPL earliest [95% CI, 2000 boot],
sufficiency, attacks/144 over banking Ajar probes, and replay ASR over the 432 banking
important_instructions traces (3 models). NO model calls."""
import os, sys, json, glob, subprocess, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"   # config driving args as grant args
os.environ["AXOR_AJAR_L2"] = "tuple"                    # kernel L2 tuple templates
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
from ajar.core.types import Candidate  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
US133 = "US133000000121212121212"
_orig_load = axor_ajar.load_config


def _patched(suite, idf, ior):
    """config-grant path config, + US133 in banking recipient O, references=false."""
    c = _orig_load(suite, idf, ior)
    if suite == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    c = dataclasses.replace(c, references=False)
    return c


axor_ajar.load_config = _patched

# ---------- (A) paper_opl over banking probes ----------
data = run_ajar.load(None)
bank_probes = [(s, p) for s, p in data if s.task.suite == "banking"]
m = P.measure(P.make("grants:L1+L2s:R0"), bank_probes)   # env forces config-grant path

# ---------- (B) replay ASR over 432 banking traces ----------
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITE = get_suite(VERSIONS["banking"], "banking")


def build_gov(prompt, plan):
    cfg = axor_ajar.load_config("banking", "context", "request-only")   # patched: +US133, refs off
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite="banking"), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def replay_asr():
    landed = runs = 0
    for model in MODELS:
        for p in sorted(glob.glob(os.path.join(ROOT, model, "banking", "user_task_*", "important_instructions", "*.json"))):
            run = json.load(open(p))
            ut = SUITE.user_tasks[run["user_task_id"]]
            prompt = next(mm["content"] for mm in run["messages"] if mm["role"] == "user")
            if isinstance(prompt, list):
                prompt = "".join(b.get("content", "") for b in prompt)
            env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
            pre = env.model_copy(deep=True)
            runtime = FunctionsRuntime(SUITE.tools)
            plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
            g = build_gov(prompt, plan)
            executed = []
            for c in [tc for mm in run["messages"] if mm["role"] == "assistant" for tc in (mm.get("tool_calls") or [])]:
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


replay = replay_asr()
row = {
    "kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
    "grant_path": "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 + AXOR_AJAR_L2=tuple (config-tuple)",
    "US133_in_banking_operator_set": True, "references": False,
    "opl": round(m["opl"]["earliest"], 4), "opl_ci95": m["ci95"]["opl"],
    "sufficiency": m["sufficiency"], "provisioned": m["provisioned"],
    "attacks": m["attacks"], "replay_asr_432": replay,
}
op = os.path.join(HERE, "results", "table8_cfgpath_us133_refsoff_c9v5.json")
json.dump(row, open(op, "w"), indent=1, default=str)
print(json.dumps(row, indent=1, default=str))
print("WROTE", op)
