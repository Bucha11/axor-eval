"""One deterministic compatibility check for every integration of the current kernel.

The same calls go through each integration (drivers.py) and through the AgentDojo
shim; nothing calls a model. Two sets:

  injecagent  every attacker call of InjecAgent's 510 direct-harm and 544
              data-stealing base cases, as experiments/injecagent/full_attack_set.py
              builds them (attacker arguments synthesized from the instruction by the
              tool's schema), under its "old" and "final" configurations. Expected
              (full_attack_set_final.json): the attacker call refused in 510/510 and
              544/544.
  agentdojo   the 581 recorded live episodes of the final AgentDojo run (o4-mini;
              A 290, B 291 with the live oracle as L4) replayed call by call under the
              frozen c9v4 configuration (and c9v5), as ajar/final_live/decisions_live.py
              replays them. Reference: results/live_final_decisions_c9v4_v.json (the
              shim's recorded verdicts).

Per call it compares, against the shim: whether the tool ran, the refusal category,
the confirmations asked, the arguments the tool ran with, and what the agent was given
back (reference names fixed by references_seed, so views compare byte for byte).

    INJECAGENT_DIR=... python compat.py [--set injecagent agentdojo] [--drivers ...]
        [--limit N] [--configs c9v4 c9v5]
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import dataclasses
import glob
import hashlib
import json
import os
import sys
import time
import types
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
AJAR = os.path.join(EXP, "ajar")
os.environ.setdefault("AXOR_CORE_REPO", os.path.join(os.path.dirname(os.path.dirname(EXP)), "..", "axor-core"))
for p in (HERE, AJAR, os.path.join(AJAR, "final_live"), os.path.join(EXP, "injecagent")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _stub_ajar() -> None:
    """axor_ajar imports Ajar's types for its Defense protocol; the functions this check
    uses (agent_args, present, spend_args, structured) do not need Ajar itself."""
    if "ajar" in sys.modules:
        return
    try:
        import ajar.core.ir  # noqa: F401
        return
    except ImportError:
        pass
    for name in ("ajar", "ajar.core", "ajar.core.ir", "ajar.core.types"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["ajar.core.ir"].TaskSpec = object
    for n in ("Candidate", "ContextRef", "Verdict"):
        setattr(sys.modules["ajar.core.types"], n, object)


_stub_ajar()
import axor_ajar  # noqa: E402
from drivers import DRIVERS  # noqa: E402

SEED = 20261015  # references_seed: the same reference names in every driver
INTEGRATIONS = ("wrap", "langchain", "claude", "openrouter")


def gate_digests() -> dict:
    """gate.py must be byte-identical in the four packages."""
    out = {}
    for pkg in ("axor_wrap", "axor_langchain", "axor_claude", "axor_openrouter"):
        mod = __import__(f"{pkg}.gate", fromlist=["gate"])
        out[pkg] = hashlib.sha256(open(mod.__file__, "rb").read()).hexdigest()
    return out


def _row(o) -> dict:
    return {"executed": o.executed, "category": o.category, "confirmations": o.confirmations,
            "ran_args": o.ran_args, "view": o.view if isinstance(o.view, (str, type(None))) else repr(o.view)}


def _diff(ref: dict, got: dict) -> list[str]:
    keys = ("executed", "category", "confirmations", "ran_args", "view")
    return [k for k in keys if ref.get(k) != got.get(k)]


# ── InjecAgent ───────────────────────────────────────────────────────────────────────
def injecagent_cases():
    import full_attack_set as fas
    from axor_core.config import GovernanceConfig

    T = fas.tools()
    core = os.environ["AXOR_CORE_REPO"]
    old = GovernanceConfig.from_yaml(os.path.join(core, "examples/injecagent/config/injecagent.yaml"))
    old = dataclasses.replace(old, integrity_default="context", integrity_origins="request-only")
    rule = fas.rule_config(old, T)
    final = fas.final_config(dataclasses.replace(rule, floor_scope="all_mutating"), T)
    cfgs = {"old": old, "final": final}
    dh = json.load(open(os.path.join(fas.DATA, "test_cases_dh_base.json")))
    ds = json.load(open(os.path.join(fas.DATA, "test_cases_ds_base.json")))
    cases = []
    for i, it in enumerate(dh):
        atk = it["Attacker Tools"][0]
        calls = [(it["User Tool"], ast.literal_eval(it["Tool Parameters"]), it["Tool Response"]),
                 (atk, fas.synth_args(T.get(atk, {}), it["Attacker Instruction"]), "ok")]
        cases.append((f"dh/{i}", it["User Instruction"], calls))
    for i, it in enumerate(ds):
        s1, s2 = it["Attacker Tools"][0], it["Attacker Tools"][1]
        calls = [(it["User Tool"], ast.literal_eval(it["Tool Parameters"]), it["Tool Response"]),
                 (s1, fas.synth_args(T.get(s1, {}), it["Attacker Instruction"]), "<the user's sensitive data>"),
                 (s2, fas.synth_args(T.get(s2, {}), it["Attacker Instruction"]), "ok")]
        cases.append((f"ds/{i}", it["User Instruction"], calls))
    return cfgs, cases


async def run_injecagent(drivers, limit):
    cfgs, cases = injecagent_cases()
    if limit:
        cases = cases[:limit] + [c for c in cases if c[0].startswith("ds/")][:limit]
    out = {}
    for cname, cfg in cfgs.items():
        cfg = dataclasses.replace(cfg, references_seed=SEED)
        per = {d: {"refused": Counter(), "cases": Counter(), "categories": Counter()} for d in drivers}
        rows = defaultdict(dict)
        for cid, task, calls in cases:
            suite = cid.split("/")[0]
            tools = sorted({c[0] for c in calls})
            for dname in drivers:
                s = DRIVERS[dname](cfg, task, None, None, tools)
                got = []
                try:
                    for tool, args, output in calls:
                        got.append(_row(await s.call(tool, args, output)))
                finally:
                    await s.close()
                rows[cid][dname] = got
                last = got[-1]
                per[dname]["cases"][suite] += 1
                per[dname]["refused"][suite] += not last["executed"]
                per[dname]["categories"][f"{suite}:{last['category']}"] += 1
        div = _divergences(rows, drivers)
        out[cname] = {"per_driver": {d: {k: dict(v) for k, v in r.items()} for d, r in per.items()},
                      "divergences": div}
        line = "  ".join(f"{d} dh {per[d]['refused']['dh']}/{per[d]['cases']['dh']} "
                         f"ds {per[d]['refused']['ds']}/{per[d]['cases']['ds']}" for d in drivers)
        print(f"[injecagent {cname}] {line}  divergences: {len(div)}", flush=True)
    return out


# ── AgentDojo: the recorded live episodes ──────────────────────────────────────────
def make_confirmer(cfg, plan):
    """decisions_live.py's live oracle, verbatim: grant arguments (dates and times
    excepted) equal to a ground-truth call; budget 5; a refused call is not re-asked."""
    from axor_core.kernel.confirm import ScriptedConfirmer
    from decisions_live import proj

    st = {"asked": 0}
    refused = set()

    def ok(action, call):
        tool, args = call
        key = json.dumps([tool, args], sort_keys=True, default=str)
        if key in refused or st["asked"] >= 5:
            return False
        st["asked"] += 1
        kinds = cfg.grant_args.get(tool, {})
        res = any(c.function == tool and proj(kinds, dict(c.args)) == proj(kinds, args) for c in plan)
        if not res:
            refused.add(key)
        return res
    return ScriptedConfirmer(ok)


def agentdojo_episodes():
    from agentdojo.task_suite.load_suites import get_suite
    from decisions_live import CALL, LIVE

    suites = {s: get_suite("v1", s) for s in ("banking", "slack", "travel", "workspace")}
    for path in sorted(glob.glob(os.path.join(LIVE, "[AB]", "pass*", "traj", "*", "*.json"))):
        rel = os.path.relpath(path, LIVE)
        d = json.load(open(path))
        suite = suites[d["suite"]]
        ut = suite.user_tasks[d["user_task_id"]]
        env = ut.init_environment(suite.load_and_inject_default_environment({}))
        plan = list(ut.ground_truth(env.model_copy(deep=True)))
        calls = []
        for m in d["messages"]:
            if m["role"] != "tool" or not m.get("tool_call"):
                continue
            mm = CALL.match(m["tool_call"])
            tool, args = mm.group(1), ast.literal_eval(mm.group(2))
            text = "".join(b.get("content", "") for b in (m.get("content") or []) if isinstance(b, dict))
            calls.append((tool, args, None if m.get("error") else text))
        yield rel, d["suite"], ut.PROMPT, plan, sorted(t.name for t in suite.tools), calls


async def run_agentdojo(drivers, limit, configs):
    from axor_core.config import GovernanceConfig

    eps = list(agentdojo_episodes())
    if limit:
        eps = eps[:limit]
    recorded = json.load(open(os.path.join(AJAR, "results", "live_final_decisions_c9v4_v.json")))
    out = {}
    for cname in configs:
        cdir = os.path.join(AJAR, f"config_m1_{cname}")
        cfgs = {s: dataclasses.replace(GovernanceConfig.from_yaml(os.path.join(cdir, f"{s}.yaml")),
                                       references_seed=SEED)
                for s in ("banking", "slack", "travel", "workspace")}
        rows = defaultdict(dict)
        per = {d: Counter() for d in drivers}
        rec_mismatch = []
        t0 = time.time()
        for rel, suite, prompt, plan, tools, calls in eps:
            cfg = cfgs[suite]
            l4 = rel.startswith("B")
            for dname in drivers:
                s = DRIVERS[dname](cfg, prompt, make_confirmer(cfg, plan) if l4 else None,
                                   axor_ajar.structured, tools)
                got = []
                try:
                    for tool, args, output in calls:
                        a = axor_ajar.agent_args(s.governor, dict(args))
                        r = _row(await s.call(tool, a, output))
                        r["tool"] = tool
                        got.append(r)
                finally:
                    await s.close()
                rows[rel][dname] = got
                per[dname]["calls"] += len(got)
                per[dname]["allowed"] += sum(r["executed"] for r in got)
                per[dname]["confirmations"] += sum(r["confirmations"] for r in got)
            if cname == "c9v4" and "shim" in rows[rel] and rel in recorded:
                ref = [(x[0], x[1], x[2], x[3]) for x in recorded[rel]["decisions"]]
                mine = [(r["tool"], r["executed"], r["category"] or "approved", r["confirmations"])
                        for r in rows[rel]["shim"]]
                if ref != mine:
                    rec_mismatch.append(rel)
        div = _divergences(rows, drivers)
        out[cname] = {"episodes": len(eps), "per_driver": {d: dict(c) for d, c in per.items()},
                      "shim_vs_recorded_mismatch": rec_mismatch, "divergences": div,
                      "seconds": round(time.time() - t0, 1)}
        line = "  ".join(f"{d} {per[d]['allowed']}/{per[d]['calls']} conf {per[d]['confirmations']}"
                         for d in drivers)
        print(f"[agentdojo {cname}] {len(eps)} episodes  {line}  divergences: {len(div)}"
              + (f"  shim vs recorded: {len(rec_mismatch)} episodes differ" if cname == "c9v4" else ""),
              flush=True)
    return out


def _divergences(rows, drivers) -> list[dict]:
    out = []
    for case, by in rows.items():
        ref = by.get("shim")
        if ref is None:
            continue
        for d in drivers:
            if d == "shim":
                continue
            got = by[d]
            for i, (a, b) in enumerate(zip(ref, got)):
                fields = _diff(a, b)
                if fields:
                    out.append({"case": case, "driver": d, "call": i, "tool": a.get("tool"),
                                "fields": fields,
                                "shim": {k: a[k] for k in fields}, "got": {k: b[k] for k in fields}})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="+", default=["injecagent", "agentdojo"])
    ap.add_argument("--drivers", nargs="+", default=["shim", *INTEGRATIONS, "daemon"])
    ap.add_argument("--configs", nargs="+", default=["c9v4", "c9v5"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    a = ap.parse_args()
    import axor_core
    head = {"gate_sha256": gate_digests(), "axor_core": axor_core.__file__, "references_seed": SEED}
    print(json.dumps(head["gate_sha256"], indent=1))
    res = {"head": head}
    if "injecagent" in a.set:
        res["injecagent"] = asyncio.run(run_injecagent(a.drivers, a.limit))
    if "agentdojo" in a.set:
        res["agentdojo"] = asyncio.run(run_agentdojo(a.drivers, a.limit, a.configs))
    os.makedirs(a.out, exist_ok=True)
    suffix = f"_limit{a.limit}" if a.limit else ""
    path = os.path.join(a.out, f"compat{suffix}.json")
    json.dump(res, open(path, "w"), indent=1, default=str)
    print("wrote", path)


if __name__ == "__main__":
    main()
