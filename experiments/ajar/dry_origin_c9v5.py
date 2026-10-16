"""Dry check (no model) for #2 origin-only: on 2 banking tasks, replay the recorded calls through
A's governor (grants L1+L2s, config args, tuple) and the origin-only governor (grants off, consequence
ceiling + floor + taxonomy KEPT) on config_m1_c9v5. Assert verdicts differ ONLY where a grant decides
(A admits via a grant that origin lacks, or A's grant gate denies where origin's gate differs).
"""
import os, sys, dataclasses, json, glob
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.task_suite.load_suites import get_suite
from ajar.core.types import Candidate
from check_wrapper import VERSIONS
from types import SimpleNamespace

suite = get_suite(VERSIONS["banking"], "banking")


def build(prompt, plan, mode):
    cfg = dataclasses.replace(axor_ajar.load_config("banking", "context", "request-only"), references=True)
    if mode == "origin":   # grants off; floor/taxonomy/consequence ceiling KEPT
        cfg = dataclasses.replace(cfg, grant_args={}, grant_templates={}, grant_quotas={}, description_sources={},
                                  description_targets={}, delegated_sources={}, list_union=False, list_args={})
        kw = cfg.as_governor_kwargs(); g = ToolCallGovernor(**kw); g.register_task(prompt); return g
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", tuple_grants=True, counters=True, confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite="banking"), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def one(utid):
    p = sorted(glob.glob(os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs", "gpt-4o-2024-05-13",
                                      "banking", utid, "important_instructions", "*.json")))[0]
    run = json.load(open(p)); ut = suite.user_tasks[utid]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list): prompt = "".join(b.get("content", "") for b in prompt)
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(
        ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {}))).model_copy(deep=True))]
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    G = {m: build(prompt, plan, m) for m in ("A", "origin")}
    ENV = {m: ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {}))) for m in ("A", "origin")}
    RT = FunctionsRuntime(suite.tools)
    rows = []
    for c in calls:
        tool, args = c["function"], dict(c["args"])
        v = {}
        for m in ("A", "origin"):
            g = G[m]; d = g.evaluate(tool, axor_ajar.agent_args(g, dict(args)))
            v[m] = ("ALLOW", str(getattr(d, "grant_source", None))) if d.allowed else ("DENY", str(getattr(d, "category", None)))
            if d.allowed:
                if getattr(d, "grant_id", None) is not None:
                    k = g.spend(d, axor_ajar.spend_args(d, dict(args)))
                    if k is not None: g.grant_store.commit(k)
                res, err = RT.run_function(ENV[m], tool, dict(args))
                if err is None: axor_ajar.present(g, d, tool_result_to_str(res), tool, dict(args), typed=res)
        differ = v["A"][0] != v["origin"][0]
        # grant-decided = A allows via a grant (L1/L2/L3/L4) while origin denies, or A's grant_gate denies
        grant_decided = (v["A"] != v["origin"]) and (
            (v["A"][0] == "ALLOW" and v["A"][1] in ("L1", "L2", "L3", "L4")) or
            (v["A"][0] == "DENY" and v["A"][1] == "grant_gate") or
            (v["origin"][0] == "DENY" and v["origin"][1] == "grant_gate"))
        rows.append({"call": tool, "A": v["A"], "origin": v["origin"], "differ": differ, "grant_decided": grant_decided})
    return utid, rows


if __name__ == "__main__":
    out = {}
    bad = []
    for utid in ("user_task_0", "user_task_3"):
        u, rows = one(utid); out[u] = rows
        print(f"\n== {u} ==")
        for r in rows:
            flag = "" if (not r["differ"] or r["grant_decided"]) else "  <-- DIFF NOT grant-decided!"
            print(f"  {r['call']:30s} A={r['A'][0]}/{r['A'][1]:14s} origin={r['origin'][0]}/{r['origin'][1]:16s} differ={r['differ']}{flag}")
            if r["differ"] and not r["grant_decided"]:
                bad.append((u, r["call"]))
    print("\nDIFFERENCES NOT explained by a grant:", bad or "none (all verdict differences are grant-decided)")
    json.dump(out, open(os.path.join(HERE, "results", "dry_origin_c9v5.json"), "w"), indent=1, default=str)
    print("DONE results/dry_origin_c9v5.json")
