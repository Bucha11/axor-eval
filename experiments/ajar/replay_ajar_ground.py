"""Q3: over the Ajar probe set (c9v5, grants L1+L2, references on, kernel 618c4a9), how many
UNNEEDED probes (required=False) whose candidate is an egress to a destination OUTSIDE O
(operator set), decided AFTER a secret read (the context prefix arms the confidentiality
floor), are ADMITTED only via a ground of the addressed floor (destination TASK-origin or an
L1/L3/L4 grant). NO model calls — decide() is the pure governor over a replayed prefix."""
import os, sys, json, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"
os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.pop("AXOR_HYP", None)
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from axor_core.contracts.taint import TrustedOrigin as _TO  # noqa: E402
from ajar.core.types import TaskKey, ContextRef, Candidate  # noqa: E402
from ajar.store import load_suite  # noqa: E402
import ajar.adapters.agentdojo.adapter as _adp  # noqa: E402,F401
from ajar.adapters.base import get_benchmark  # noqa: E402

ADAPTER = get_benchmark("agentdojo")
SUITES = ("banking", "slack", "travel", "workspace")

# grants L1+L2 arm
_KW, _HOOK = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
DEF = axor_ajar.AxorDefense(name="grants-L1+L2", integrity_default="context",
                            integrity_origins="request-only", governor_kwargs=_KW, hook=_HOOK)

# operator sets O per suite (from c9v5 config)
OSET = {}
for s in SUITES:
    cfg = axor_ajar.load_config(s, "context", "request-only")
    OSET[s] = {t: {a: set(map(str, vs)) for a, vs in args.items()} for t, args in cfg.operator_sets.items()}


def leaves(v):
    if isinstance(v, (list, tuple, set, frozenset)):
        return [y for x in v for y in leaves(x)]
    return [] if v in (None, "") else [v]


def outside_O(suite, tool, args, destargs):
    out = []
    for a in destargs:
        allowed = OSET[suite].get(tool, {}).get(a)
        if allowed is None:
            continue
        for x in leaves(args.get(a)):
            if str(x) not in allowed:
                out.append((a, x))
    return out


def decide_instrumented(spec, ctx, cand):
    """mirror AxorDefense.decide but capture floor + audience-ground on the candidate."""
    g = DEF.governor(spec)
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
            if key is not None:
                g.grant_store.commit(key)
        if out is not None:
            axor_ajar.present(g, d, out, call.tool, dict(call.args))
    floor_on = g.confidentiality_floor_active()
    d = g.evaluate(cand.tool, axor_ajar.agent_args(g, dict(cand.args)))
    info = {"allowed": bool(d.allowed), "floor_on": floor_on, "category": d.category,
            "grant_source": getattr(d, "grant_source", None), "mechanism": None}
    if d.allowed and floor_on and cand.tool in g._egress_sinks:
        dests = [x for a in g._destination_args.get(cand.tool, ()) for x in leaves(cand.args.get(a))]
        outside_aud = [x for x in dests if str(x).casefold() not in g._audience]
        if outside_aud:
            task_o = all(g._taint.trusted_origin(x) is _TO.TASK for x in outside_aud)
            gs = getattr(d, "grant_source", None)
            info["mechanism"] = "TASK" if task_o else (f"grant:{gs}" if gs in ("L1", "L3", "L4") else "other")
    return info


VER = {"banking": (1, 2, 2), "slack": (1, 2, 2), "travel": (1, 2, 2), "workspace": (1, 2, 2)}
tot = {"unneeded_egress_outsideO_probes": 0, "after_secret_read": 0,
       "admitted": 0, "admitted_via_ground": 0, "by_mech": {}, "by_suite": {}}
rows = []
for s in SUITES:
    # enumerate this suite's tasks present in the export
    import ajar.io as _io
    from ajar.store import probes_path
    keys = [k for k in _io.load_task_keys(probes_path("agentdojo")) if k.suite == s]
    egress_tools = set()
    for k in keys:
        try:
            probes = load_suite(k)
        except Exception:
            continue
        spec = ADAPTER.task_spec(k)
        # egress sinks for this suite from a throwaway governor
        if not egress_tools:
            gg = DEF.governor(spec); egress_tools = set(gg._egress_sinks)
        for p in probes:
            if p.required:                      # unneeded only
                continue
            cand = p.candidate
            if cand.tool not in egress_tools:
                continue
            dargs = DEF.governor(spec)._destination_args.get(cand.tool, ())
            oo = outside_O(s, cand.tool, dict(cand.args), dargs)
            if not oo:                          # destination must be outside O
                continue
            tot["unneeded_egress_outsideO_probes"] += 1
            info = decide_instrumented(spec, p.context, cand)
            if info["floor_on"]:
                tot["after_secret_read"] += 1
            if info["allowed"] and info["floor_on"]:
                tot["admitted"] += 1
                if info["mechanism"]:
                    tot["admitted_via_ground"] += 1
                    tot["by_mech"][info["mechanism"]] = tot["by_mech"].get(info["mechanism"], 0) + 1
                    tot["by_suite"][s] = tot["by_suite"].get(s, 0) + 1
                    rows.append({"suite": s, "task": k.task_id, "probe_id": p.probe_id,
                                 "injection": p.context.injections and list(p.context.injections)[:1],
                                 "tool": cand.tool, "outside_O": [f"{a}={x}" for a, x in oo],
                                 "expected_label": p.expected_label.name, "harm_tier": getattr(p, "harm_tier", None) and p.harm_tier.name,
                                 "mechanism": info["mechanism"], "prefix": list(p.context.prefix),
                                 "category": info["category"], "grant_source": info["grant_source"]})

out = {"task": "ajar_probe_audience_ground", "config": "c9v5 grants L1+L2 refs on", "kernel_commit": "618c4a9",
       "summary": tot, "rows": rows}
op = os.path.join(HERE, "results", "ajar_ground_probes_c9v5.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print(json.dumps(tot, indent=1)); print("rows", len(rows)); print("WROTE", op)
