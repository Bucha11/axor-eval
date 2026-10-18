"""Checks 1 & 2 over SAVED setup (no model): provisioning diff ROPE vs axor on the 52 gradeable
tasks, the named-sender dependence split, axor deny gate + value origin + request prompt per call,
and oracle-L4 confirmation. f227951 + config_m1_c9v5, config-tuple, references on."""
import os, sys, json, subprocess
HERE = "/home/user/ajar-wt/experiments/ajar"
SC = "/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad"
WT = os.environ.get("KERNEL_WT", os.path.join(SC, "k_new"))
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"; os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
ROPE_SRC = os.path.join(SC, "ext/rope/src")
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, ROPE_SRC)
import axor_ajar, run_ajar  # noqa: E402
import rope_ajar  # noqa: E402
from rope import origin as O  # noqa: E402
from agentdojo.functions_runtime import FunctionCall  # noqa: E402
from ajar.runner import run_defense  # noqa: E402
from ajar.score.scorer import score  # noqa: E402
from ajar.core.types import Label, Verdict  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
data = [(s, p) for s, p in run_ajar.load(None) if s.task.suite in ("banking", "slack", "travel") and s.is_gradeable]
GA = {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args) for s in ("banking", "slack", "travel")}
rope = rope_ajar.RopeDefense("rope", "opus")
axor = axor_ajar.grants_defense("grants:L1+L2s", "L1+L2s", grant_args=GA)
oracle = axor_ajar.grants_defense("grants:L1+L2s+L4:oracle", "L1+L2s+L4", grant_args=GA, confirm="oracle")


def prov_set(defense):
    s = set()
    for spec, probes in data:
        res = run_defense(defense, spec, probes)
        if score(defense.name, probes, res).gate_passed:
            s.add(str(spec.task))
    return s


rope_prov, axor_prov = prov_set(rope), prov_set(axor)
rope_only = sorted(rope_prov - axor_prov)
axor_only = sorted(axor_prov - rope_prov)


def rope_leg(spec, ctx, tool, args):
    floor, scopes, tools = rope._suite(spec.task.suite)
    origin_map = {}; tracker = O.OriginTracker(origin_map); messages = []
    for i, (call, out) in enumerate(axor_ajar.PREFIXES.outputs(spec, ctx)):
        fc = FunctionCall(function=call.tool, args=dict(call.args), id=f"p{i}")
        messages.append({"role": "tool", "content": out if out is not None else "", "tool_call": fc})
    tracker.query(spec.prompt, None, None, messages, {})
    pid = O.tokenize_identifiers(spec.prompt)
    legs = {}
    for a, v in args.items():
        for one in (v if isinstance(v, (list, tuple)) else [v]):
            if not isinstance(one, str):
                continue
            vtok = O.tokenize_identifiers(one, split_composites=False) or {one}
            tag = None
            if vtok & pid:
                tag = "prompt"
            else:
                rec = origin_map.get(O.RECORD_SOURCE_KEY)
                if rec and not rec["injectable"] and (vtok & rec["ids"]):
                    tag = "record"
                else:
                    for src, e in origin_map.items():
                        if e["injectable"] or src == O.RECORD_SOURCE_KEY:
                            continue
                        if vtok & e["ids"]:
                            tag = f"source(named):{src[:30]}"; break
            if tag:
                legs.setdefault(a, []).append((str(one)[:40], tag))
    return legs


def value_origin(spec, ctx, value):
    vl = str(value).casefold()
    if len(vl) > 2 and vl in (spec.prompt or "").casefold():
        return "request"
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        if out and vl in str(out).casefold():
            return "read-record"
    return "own/other"


def axor_eval(defense, spec, ctx, cand):
    g = defense.governor(spec)
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
        if getattr(d, "grant_id", None) is not None:
            k = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
            if k is not None:
                g.grant_store.commit(k)
        if out is not None:
            axor_ajar.present(g, d, out, call.tool, dict(call.args))
    d = g.evaluate(cand.tool, axor_ajar.agent_args(g, dict(cand.args)))
    return d


by_task = {str(s.task): (s, p) for s, p in data}

# classify rope_only tasks by named-sender dependence; collect denied-call rows
named_dep = {}; rows_by_task = {}
for t in rope_only:
    spec, probes = by_task[t]
    uses_named = False; rws = []
    for p in probes:
        if not (p.scored and p.expected_label is Label.ALLOW and p.required):
            continue
        rv = rope.decide(spec, p.context, p.candidate)
        d = axor_eval(axor, spec, p.context, p.candidate)
        if rv is Verdict.ALLOW and not d.allowed:
            legs = rope_leg(spec, p.context, p.candidate.tool, dict(p.candidate.args))
            if any(tag.startswith("source(named)") for lst in legs.values() for _, tag in lst):
                uses_named = True
            origins = {a: value_origin(spec, p.context, (vv if not isinstance(vv, (list, tuple)) else (vv[0] if vv else "")))
                       for a, vv in dict(p.candidate.args).items()}
            # oracle re-eval
            od = axor_eval(oracle, spec, p.context, p.candidate)
            rws.append({"tool": p.candidate.tool,
                        "args": {k: str(v)[:50] for k, v in dict(p.candidate.args).items()},
                        "axor_gate": d.category, "rope_leg": legs, "value_origin": origins,
                        "oracle_allowed": bool(od.allowed), "oracle_grant_source": str(getattr(od, "grant_source", None))})
    named_dep[t] = uses_named; rows_by_task[t] = {"prompt": spec.prompt, "rows": rws}

non_named = [t for t in rope_only if not named_dep[t]]

# axor_only: why rope denies
axor_only_detail = []
for t in axor_only:
    spec, probes = by_task[t]
    denied = []
    for p in probes:
        if not (p.scored and p.expected_label is Label.ALLOW and p.required):
            continue
        rv = rope.decide(spec, p.context, p.candidate)
        if rv is not Verdict.ALLOW:
            denied.append({"tool": p.candidate.tool, "args": {k: str(v)[:50] for k, v in dict(p.candidate.args).items()},
                           "rope_verdict": str(rv)})
    axor_only_detail.append({"task": t, "prompt": spec.prompt, "rope_denied_required_calls": denied})

# oracle provisions all 10?
oracle_prov = prov_set(oracle)
oracle_covers_10 = {t: (t in oracle_prov) for t in non_named}

out = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on",
       "rope_provisioned": f"{len(rope_prov)}/52", "axor_provisioned": f"{len(axor_prov)}/52",
       "oracle_provisioned": f"{len(oracle_prov)}/52",
       "n_rope_only": len(rope_only), "rope_only_tasks": rope_only,
       "n_axor_only": len(axor_only), "axor_only_tasks": axor_only, "axor_only_detail": axor_only_detail,
       "named_sender_dependent": {t: named_dep[t] for t in rope_only},
       "n_non_named_sender": len(non_named), "non_named_sender_tasks": non_named,
       "non_named_detail": {t: rows_by_task[t] for t in non_named},
       "oracle_covers_each_of_non_named": oracle_covers_10}
op = os.path.join(HERE, "results", "rope_axor_diff_check.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print("rope", len(rope_prov), "axor", len(axor_prov), "oracle", len(oracle_prov),
      "| rope_only", len(rope_only), "axor_only", len(axor_only), "non_named", len(non_named))
print("axor_only:", axor_only)
print("non_named:", non_named)
for t in non_named:
    for r in rows_by_task[t]["rows"]:
        print(" ", t.split("/")[-1], r["tool"], "gate", r["axor_gate"], "| oracle", r["oracle_allowed"], r["oracle_grant_source"], "| origins", r["value_origin"])
print("oracle covers 10:", oracle_covers_10)
print("WROTE", op)
