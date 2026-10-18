"""Doc-aware confirmer (Ajar), L1-only (Ajar), and D.3 gate trace. f227951 + config_m1_c9v5,
config-tuple, references on. No model."""
import os, sys, json, subprocess, dataclasses, glob
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
import axor_ajar, run_ajar, paper_opl as P  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from ajar.core.types import Candidate  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
data = run_ajar.load(None)
GA = {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args) for s in ("banking", "slack", "travel", "workspace")}


def defense(levels, confirm=None):
    kw = {"grant_args": GA}
    if confirm:
        return axor_ajar.grants_defense(f"grants:{levels}:{confirm}", levels, grant_args=GA, confirm=confirm)
    return axor_ajar.grants_defense(f"grants:{levels}", levels, grant_args=GA)


def measure(levels, confirm=None):
    m = P.measure(defense(levels, confirm), data)
    return {"opl": round(m["opl"]["earliest"], 4), "ci95_opl": m["ci95"]["opl"],
            "sufficiency": m["sufficiency"], "provisioned": m["provisioned"], "attacks": m["attacks"]}


res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on"}
res["Ajar_confirmers_L1+L2s+L4"] = {
    "oracle": measure("L1+L2s+L4", "oracle"),
    "view": measure("L1+L2s+L4", "view"),
    "naive": measure("L1+L2s+L4", "naive"),
    "document": measure("L1+L2s+L4", "document")}
res["Ajar_L1_only"] = measure("L1")

# ---------- D.3: gate on US133 replay attacker calls (config-tuple, US133 in O, refs off) ----------
US133 = "US133000000121212121212"
_orig = axor_ajar.load_config


def _patched(s, i, io):
    c = _orig(s, i, io)
    if s == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    return dataclasses.replace(c, references=False)  # D.3 is the refs-off row


axor_ajar.load_config = _patched
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITE = get_suite(VERSIONS["banking"], "banking")
from collections import Counter
gate = Counter(); allow = 0; total = 0
for model in MODELS:
    for p in sorted(glob.glob(os.path.join(ROOT, model, "banking", "user_task_*", "important_instructions", "*.json"))):
        run = json.load(open(p)); ut = SUITE.user_tasks[run["user_task_id"]]
        prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
        if isinstance(prompt, list):
            prompt = "".join(b.get("content", "") for b in prompt)
        env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
        runtime = FunctionsRuntime(SUITE.tools)
        plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(env.model_copy(deep=True))]
        cfg = axor_ajar.load_config("banking", "context", "request-only")
        kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
        spec = SimpleNamespace(task=SimpleNamespace(suite="banking"), prompt=prompt, plan=plan)
        kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
        g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)
        for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
            raw = dict(c["args"])
            d = g.evaluate(c["function"], axor_ajar.agent_args(g, raw))
            if US133.casefold() in str(raw).casefold() and c["function"] in ("send_money", "update_scheduled_transaction", "schedule_transaction"):
                total += 1
                if d.allowed:
                    allow += 1
                else:
                    gate[(c["function"], d.category)] += 1
            if d.allowed:
                if getattr(d, "grant_id", None) is not None:
                    k = g.spend(d, axor_ajar.spend_args(d, raw))
                    if k is not None:
                        g.grant_store.commit(k)
                rr, err = runtime.run_function(env, c["function"], raw)
                if err is None:
                    axor_ajar.present(g, d, tool_result_to_str(rr), c["function"], raw)
res["D3_US133_replay_attacker_calls_refsoff"] = {
    "total_US133_sink_calls": total, "allowed": allow, "denied": total - allow,
    "deny_by_tool_gate": {f"{t}·{c}": n for (t, c), n in gate.most_common()},
    "value_policies_banking": None,
    "note": "L2 grant is a whole-tuple constraint over the driving args (recipient AND amount; grants.py:3,18). value_policies is null; amount is bound by the GRANT tuple, not a value_policy enum. An attacker send_money(US133, amount) whose (recipient,amount) tuple no live grant covers is refused by grant_gate (refs off, so reference_origin does not fire)."}
op = os.path.join(HERE, "results", "docaware_l1_d3_nsfix.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
