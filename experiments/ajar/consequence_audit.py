"""config_rule, no change: consequence class per tool, ceiling per degradation level,
consequence denials (Ajar probes, live v4/v5, 288 benign), and the §2.3 taxonomy of each
driving arg on AgentDojo's reference plans (prompt-given / known-set / one-off).

    AXOR_CORE_REPO=<kernel> python consequence_audit.py  -> results/consequence_audit.json
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter, defaultdict

CORE = os.environ["AXOR_CORE_REPO"]
sys.path.insert(0, CORE)
HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402
from axor_core.contracts.degradation import DegradationLevel  # noqa: E402
from axor_core.degradation.engine import _LOCKED_ALLOWED_TOOLS  # noqa: E402
from axor_core.policy.consequence import consequence_class, is_consequence_classified  # noqa: E402

SUITES = ("banking", "slack", "travel", "workspace")
CEILING = ConsequenceClass.CONSEQUENTIAL  # ToolCallGovernor default; no config sets it


def cfg(s):
    return GovernanceConfig.from_yaml(os.path.join(HERE, "config_rule", f"{s}.yaml"))


def level_admits(tool, level):
    """What a degradation level does to a tool BY NAME (DegradationEngine.tool_denial);
    the consequence ceiling is not touched by any level."""
    if level >= DegradationLevel.LOCKED:
        return tool.lower() in _LOCKED_ALLOWED_TOOLS
    if level == DegradationLevel.RESTRICTED:  # only for a quarantined source
        return tool.lower() not in {"bash", "shell", "execute", "run", "write", "edit", "multiedit"}
    return True


def leaves(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from leaves(x)
    elif isinstance(v, (list, tuple, set)):
        for x in v:
            yield from leaves(x)
    elif v is not None and str(v) != "":
        yield str(v)


def main():
    from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite

    O = json.load(open(os.path.join(R, "operator_o.json")))
    out = {"ceiling": CEILING.name, "tools": {}, "denials": {}, "taxonomy": {}}

    # 1-2: class and per-level admission
    for s in SUITES:
        c = cfg(s)
        suite = get_suite("v1", s)
        rows = {}
        for t in sorted(f.name for f in suite.tools):
            cls = consequence_class(t, overrides=c.consequence_overrides, strict=False)
            src = ("override" if t.lower() in {k.lower() for k in c.consequence_overrides}
                   else "table" if is_consequence_classified(t) else "default/heuristic")
            sink = t in c.egress_sinks or t in c.integrity_sinks
            rows[t] = {"class": cls.name, "source": src, "sink": sink,
                       "over_ceiling": cls > CEILING,
                       "levels": {lv.name: ("consequence-denied" if cls > CEILING else "ok")
                                  if level_admits(t, lv) else "frozen-by-level"
                                  for lv in DegradationLevel}}
        out["tools"][s] = rows

    # 3: consequence denials
    den = {}
    for f in ("rl_v4_rule7base", "rl_v5_rule7base", "rl_benign_rule7base_a", "rl_benign_rule7base_b"):
        cnt = Counter()
        for r in json.load(gzip.open(os.path.join(R, "replay_live", f + ".json.gz"))):
            for x in r["calls"]:
                if not x["allowed"] and x["category"] == "consequence_gate":
                    cnt[(r["suite"], x["tool"], r["task"])] += 1
        den[f] = [{"suite": a, "tool": b, "task": t, "n": n} for (a, b, t), n in sorted(cnt.items())]
    # Ajar: the consequence gate is gate 1 and content/state-free in the governor, so every
    # probe on an over-ceiling tool is a consequence denial in every config (a)/(b)/(c)
    over = {(s, t) for s in SUITES for t, r in out["tools"][s].items() if r["over_ceiling"]}
    ajar = Counter()
    for line in open(os.path.join(os.environ.get("AJAR_ROOT", "/home/user/Ajar"),
                                  "benchmarks/agentdojo/data/probes.jsonl")):
        p = json.loads(line)
        if not p.get("scored", True):
            continue
        s = p["task"]["suite"] if isinstance(p.get("task"), dict) else p["task_id"].split("/")[0]
        tool = p["candidate"]["tool"]
        if (s, tool) in over:
            ajar[(s, tool, p.get("expected_label"), p.get("fault_class"))] += 1
    den["ajar_probes"] = [{"suite": a, "tool": b, "label": l, "fault": f, "n": n}
                          for (a, b, l, f), n in sorted(ajar.items())]
    out["denials"] = den

    # 4: §2.3 taxonomy of each driving arg on the reference plans
    tax = defaultdict(Counter)
    examples = defaultdict(list)
    for s in SUITES:
        c = cfg(s)
        o_vals = {v.casefold() for vs in O[s]["O"].values() for v in vs}
        suite = get_suite("v1", s)
        rt = FunctionsRuntime(suite.tools)
        for ut_id, ut in suite.user_tasks.items():
            env = suite.load_and_inject_default_environment({})
            env = ut.init_environment(env)
            prompt = ut.PROMPT.casefold()
            reads = ""
            for call in ut.ground_truth(env.model_copy(deep=True)):
                drv = c.driving_args.get(call.function)
                if drv:
                    for a in drv:
                        for v in leaves(call.args.get(a)):
                            cv = v.casefold()
                            p, k, rd = cv in prompt, cv in o_vals, cv in reads.casefold()
                            cat = ("prompt-given" if p else "known-set" if k
                                   else "one-off" if rd else "neither")
                            key = f"{s}/{call.function}.{a}"
                            tax[key][cat] += 1
                            if p and k:
                                tax[key]["(prompt∩O)"] += 1
                            if cat in ("one-off", "neither") and len(examples[key]) < 3:
                                examples[key].append(f"{ut_id}: {v[:40]}")
                res, err = rt.run_function(env, call.function, dict(call.args))
                reads += "\n" + (tool_result_to_str(res) if err is None else "")
        for t, args in c.driving_args.items():
            for a in args:
                tax.setdefault(f"{s}/{t}.{a}", Counter())
    out["taxonomy"] = {k: {"counts": dict(v), "examples": examples.get(k, [])} for k, v in sorted(tax.items())}
    json.dump(out, open(os.path.join(R, "consequence_audit.json"), "w"), indent=1)

    for s in SUITES:
        print(f"\n== {s}")
        for t, r in out["tools"][s].items():
            print(f"  {t:34} {r['class']:13} ({r['source']}){' sink' if r['sink'] else ''}"
                  f"{'  OVER CEILING' if r['over_ceiling'] else ''}")
    print("\nlevels (any tool): ", {lv.name: level_admits('send_money', lv) for lv in DegradationLevel})
    for f, rows in den.items():
        print(f"\n## consequence denials {f}: {sum(r['n'] for r in rows)}")
        for r in rows[:30]:
            print("  ", r)
    print("\n## taxonomy")
    for k, v in out["taxonomy"].items():
        print(f"  {k:55} {v['counts']}  {v['examples']}")


if __name__ == "__main__":
    main()
