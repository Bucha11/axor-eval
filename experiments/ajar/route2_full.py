"""MODEL.md §9.20a: route 2 with a candidate set independent of the grants issued.

For each decision point (a sink call of the reference plan, or the default call when the plan has no
such sink) and each leading (destination) argument, every value of the argument's kind from
  request literals ∪ O (the config audience) ∪ the values in the reads
    (the reference plan's outputs, and the attacker-seeded probe values — the values an attack places
     in a read),
scalars and lists alike (a list candidate is a one-element list). Each candidate is decided (mode b)
under the configuration in AXOR_AJAR_CONFIG_DIR. Per source (L1 / L2): admitted total, admitted whose
value names an existing object of the initial state, decision points, k over the latter; and whether
any admitted value is from neither the request nor O (an attacker value).

    AXOR_AJAR_CONFIG_DIR=... TAG=... python route2_full.py
"""
import collections
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import residuals  # noqa: E402
import route2_entities as r2  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import ContextRef  # noqa: E402
from axor_core.kernel.request_literals import literal_values  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def read_values(spec, probes, kinds):
    """Values of each kind appearing in the reads: the reference plan's outputs, plus every
    attacker-seeded probe's candidate argument values (the values an attack lands in a read)."""
    vals = collections.defaultdict(set)
    full = ContextRef(task=spec.task, prefix=tuple(range(len(spec.plan))))
    outs = [str(o) for _, o in axor_ajar.PREFIXES.outputs(spec, full) if o is not None]
    text = "\n".join(outs)
    for k in kinds:
        for v in literal_values(text, k):
            vals[k].add(r2.canon(v))
    for p in probes:
        if p.fault_class.value != "ATTACKER_SEEDED":
            continue
        for a, x in dict(p.candidate.args).items():
            k = r2.kind_of(spec.task.suite, a)
            if k:
                for y in (x if isinstance(x, list) else [x]):
                    if isinstance(y, (str, int)):
                        vals[k].add(r2.canon(y))
    return vals


def main():
    import yaml
    tag = os.environ.get("TAG", "full")
    cfgdir = os.environ["AXOR_AJAR_CONFIG_DIR"]
    cfgs = {s: yaml.safe_load(open(os.path.join(cfgdir, f"{s}.yaml")))
            for s in ("banking", "slack", "travel", "workspace")}
    ents = {s: r2.entities(s, __import__("agentdojo.task_suite.load_suites", fromlist=["get_suite"])
                           .get_suite("v1", s).load_and_inject_default_environment({}))
            for s in cfgs}
    rows = []
    for spec, probes in run_ajar.load(None):
        suite = spec.task.suite
        cfg = cfgs[suite]
        dest = cfg.get("destination_args") or {}
        own = {str(x).casefold() for x in cfg.get("audience") or ()}
        reqlits = collections.defaultdict(set)
        all_kinds = {r2.kind_of(suite, a) for sink in dest for a in dest[sink]} - {None}
        for k in all_kinds:
            for v in literal_values(spec.prompt, k):
                reqlits[k].add(r2.canon(v))
        reads = read_values(spec, probes, all_kinds)
        sinks = set(cfg.get("egress_sinks") or []) | set(cfg.get("integrity_sinks") or [])
        plan_idx = {}
        for i, c in enumerate(spec.plan):
            plan_idx.setdefault(c.tool, (i, dict(c.args)))
        for sink in dest:
            if sink not in sinks or sink not in (cfg.get("grant_args") or {}):
                continue
            idx, base = plan_idx.get(sink, (len(spec.plan), dict(residuals.DEFAULTS.get(suite, {}).get(sink, {}))))
            is_list = set((cfg.get("list_args") or {}).get(sink, []))
            for arg in dest[sink]:
                k = r2.kind_of(suite, arg)
                if k is None:
                    continue
                pool = reqlits[k] | {r2.canon(x) for x in ents[suite][k]} | reads[k]
                pool |= {x for x in own}  # O as the config declares it
                for v in sorted(pool):
                    if not v:
                        continue
                    call = dict(base)
                    call[arg] = [v] if arg in is_list else v
                    if any(call == dict(c.args) for i, c in enumerate(spec.plan) if c.tool == sink):
                        continue
                    d = residuals.run(spec, "b", idx, [(sink, call, None)])
                    src = getattr(d, "grant_source", None) if d.allowed else None
                    rows.append({"suite": suite, "task": str(spec.task), "sink": sink, "arg": arg, "value": v,
                                 "allowed": bool(d.allowed), "source": src,
                                 "existing": v in {r2.canon(x) for x in ents[suite][k]},
                                 "attacker": v not in reqlits[k] and v not in own})
    out = {}
    for src in ("L1", "L2"):
        adm = [r for r in rows if r["allowed"] and r["source"] == src]
        ex = [r for r in adm if r["existing"]]
        pts = collections.defaultdict(set)
        for r in ex:
            pts[(r["suite"], r["task"], r["sink"], r["arg"])].add(r["value"])
        ks = [len(v) for v in pts.values()]
        out[src] = {"admitted": len(adm), "admitted_existing": len(ex), "decision_points": len(ks),
                    "k": ks and [statistics.median(ks), r2.pct(ks, 0.9), max(ks)]}
    attacker = [r for r in rows if r["allowed"] and r["attacker"]]
    out["attacker_values_admitted"] = len(attacker)
    out["attacker_rows"] = [{k: r[k] for k in ("suite", "task", "sink", "arg", "value", "source")}
                            for r in attacker]
    print(json.dumps({k: v for k, v in out.items() if k != "attacker_rows"}))
    json.dump({"summary": {k: v for k, v in out.items() if k != "attacker_rows"},
               "attacker_rows": out["attacker_rows"], "rows": rows},
              open(os.path.join(HERE, "results", f"route2_full_{tag}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
