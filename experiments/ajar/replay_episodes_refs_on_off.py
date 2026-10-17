"""READ-ONLY (no model, no kernel/config writes). Per-episode replay diff over the 432 banking
important_instructions traces, kernel 618c4a9 + config_m1_c9v5, CONFIG-tuple grant path
(GRANT_ARGS_FROM_CONFIG=1, L2=tuple), US133 in banking recipient O. Two governors differing ONLY
by references on/off. For every trace records (model, user_task, injection, landed) and, for each
recorded tool call, (tool, allowed, category) under both. Then lists the landed episodes of each
run and the episodes that land ONLY with refs on, with the gate that denies their US133 call when
refs are off."""
import os, sys, json, glob, subprocess, dataclasses
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
REFS = {"on": True}


def _patched(suite, idf, ior):
    c = _orig_load(suite, idf, ior)
    if suite == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    c = dataclasses.replace(c, references=REFS["on"])
    return c


axor_ajar.load_config = _patched
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITE = get_suite(VERSIONS["banking"], "banking")


def build_gov(prompt, plan):
    cfg = axor_ajar.load_config("banking", "context", "request-only")
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite="banking"), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def replay_one(path):
    """Return dict with trace meta, landed bool, and per-call (tool,allowed,category,has_us133)."""
    run = json.load(open(path))
    ut = SUITE.user_tasks[run["user_task_id"]]
    prompt = next(mm["content"] for mm in run["messages"] if mm["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(SUITE.tools)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    g = build_gov(prompt, plan)
    executed, calls = [], []
    for c in [tc for mm in run["messages"] if mm["role"] == "assistant" for tc in (mm.get("tool_calls") or [])]:
        fed = axor_ajar.agent_args(g, dict(c["args"]))
        d = g.evaluate(c["function"], fed)
        has133 = US133.casefold() in str(dict(c["args"])).casefold()
        calls.append({"tool": c["function"], "allowed": bool(d.allowed), "category": d.category,
                      "has_us133": has133, "args": dict(c["args"])})
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
    landed = inj is not None and bool(SUITE._check_injection_task_security(inj, [], pre, env, executed))
    us133_in_prompt = US133.casefold() in prompt.casefold()
    return {"path": os.path.relpath(path, ROOT), "model": os.path.relpath(path, ROOT).split("/")[0],
            "user_task": run["user_task_id"], "injection": run.get("injection_task_id"),
            "landed": landed, "us133_in_prompt": us133_in_prompt, "calls": calls}


def run_all():
    out = []
    for model in MODELS:
        for p in sorted(glob.glob(os.path.join(ROOT, model, "banking", "user_task_*", "important_instructions", "*.json"))):
            out.append(replay_one(p))
    return out


REFS["on"] = True
on = run_all()
REFS["on"] = False
off = run_all()
assert len(on) == len(off)
by_off = {r["path"]: r for r in off}


def us133_calls(r):
    return [{"tool": c["tool"], "allowed": c["allowed"], "category": c["category"],
             "recipient": c["args"].get("recipient"), "amount": c["args"].get("amount")}
            for c in r["calls"] if c["has_us133"]]


landed_on = [r for r in on if r["landed"]]
landed_off = [r for r in off if r["landed"]]
only_on = [r for r in on if r["landed"] and not by_off[r["path"]]["landed"]]

summary = {
    "kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
    "grant_path": "GRANT_ARGS_FROM_CONFIG=1 + L2=tuple (config-tuple), US133 in banking O",
    "landed_refs_on": len(landed_on), "landed_refs_off": len(landed_off),
    "landed_only_refs_on": len(only_on),
    "landed_refs_on_episodes": [
        {"model": r["model"], "user_task": r["user_task"], "injection": r["injection"],
         "us133_in_prompt": r["us133_in_prompt"], "us133_calls": us133_calls(r)} for r in landed_on],
    "landed_refs_off_episodes": [
        {"model": r["model"], "user_task": r["user_task"], "injection": r["injection"],
         "us133_in_prompt": r["us133_in_prompt"], "us133_calls": us133_calls(r)} for r in landed_off],
    "only_refs_on_episodes": [
        {"model": r["model"], "user_task": r["user_task"], "injection": r["injection"],
         "us133_in_prompt": r["us133_in_prompt"],
         "us133_calls_refs_on": us133_calls(r),
         "us133_calls_refs_off": us133_calls(by_off[r["path"]])} for r in only_on],
}
op = os.path.join(HERE, "results", "replay_episodes_refs_on_off.json")
json.dump(summary, open(op, "w"), indent=1, default=str)

print("landed refs on=%d  refs off=%d  only-on=%d" % (len(landed_on), len(landed_off), len(only_on)))
import collections
print("\n-- only-refs-on episodes (task x injection) --")
tc = collections.Counter((r["user_task"], r["injection"]) for r in only_on)
for (ut, inj), n in tc.most_common():
    print("  %s x %s : %d" % (ut, inj, n))
print("\n-- only-on: us133_in_prompt breakdown --", collections.Counter(r["us133_in_prompt"] for r in only_on))
print("\n-- only-on: refs-off deny category on US133 calls --")
cat = collections.Counter()
for r in only_on:
    for c in us133_calls(by_off[r["path"]]):
        if not c["allowed"]:
            cat[(c["tool"], c["category"])] += 1
for (t, c), n in cat.most_common():
    print("  %s : %s  x%d" % (t, c, n))
print("\n-- landed refs-off episodes --")
for r in landed_off:
    print("  ", r["model"], r["user_task"], r["injection"], "us133_in_prompt=%s" % r["us133_in_prompt"])
print("WROTE", op)
