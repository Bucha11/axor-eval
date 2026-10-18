"""ROPE (cached opus router) vs axor (f227951 + config_m1_c9v5, config-tuple L1+L2s, references on)
over the 52 gradeable ROPE tasks (banking/slack/travel). No model.

Part 2: tasks ROPE provisions but axor does not; for each required ALLOW call there, ROPE's admitting
leg (prompt / record / source(named) / const / always-allowed), axor's deny gate, and the value's
origin (request / read-record / own)."""
import os, sys, json, subprocess, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
SC = "/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad"
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"; os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ["ROPE_SRC"] = os.path.join(SC, "ext/rope/src")
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, os.environ["ROPE_SRC"])
import axor_ajar, run_ajar, paper_opl as P  # noqa: E402
import rope_ajar  # noqa: E402
from rope import origin as O, policy_synthesis as PS  # noqa: E402
from rope.scopes_io import load_router_scopes  # noqa: E402
from rope.enforce import Enforcer  # noqa: E402
from agentdojo.functions_runtime import FunctionCall  # noqa: E402
from ajar.runner import run_defense  # noqa: E402
from ajar.score.scorer import score  # noqa: E402
from ajar.core.types import Label, Verdict  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
data = [(s, p) for s, p in run_ajar.load(None) if s.task.suite in ("banking", "slack", "travel") and s.is_gradeable]
GA = {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args) for s in ("banking", "slack", "travel")}
rope = rope_ajar.RopeDefense("rope", "opus")
axor = axor_ajar.grants_defense("grants:L1+L2s", "L1+L2s", grant_args=GA)


def provisioned_set(defense):
    s = set()
    for spec, probes in data:
        res = run_defense(defense, spec, probes)
        if score(defense.name, probes, res).gate_passed:
            s.add(str(spec.task))
    return s


rope_prov = provisioned_set(rope)
axor_prov = provisioned_set(axor)
rope_only = sorted(rope_prov - axor_prov)


# ---- ROPE admitting leg for a given (spec, ctx, cand, arg, value) ----
def rope_leg(spec, ctx, tool, args):
    suite = spec.task.suite
    floor, scopes, tools = rope._suite(suite)
    origin_map = {}
    tracker = O.OriginTracker(origin_map)
    messages = []
    for i, (call, out) in enumerate(axor_ajar.PREFIXES.outputs(spec, ctx)):
        fc = FunctionCall(function=call.tool, args=dict(call.args), id=f"p{i}")
        messages.append({"role": "tool", "content": out if out is not None else "", "tool_call": fc})
    tracker.query(spec.prompt, None, None, messages, {})
    pid = O.tokenize_identifiers(spec.prompt)
    legs = {}
    for a, v in args.items():
        vals = v if isinstance(v, (list, tuple)) else [v]
        for one in vals:
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
    return legs or {"(no identifier arg)": []}


def value_origin(spec, ctx, value):
    vl = str(value).casefold()
    if len(vl) > 2 and vl in (spec.prompt or "").casefold():
        return "request"
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        if out and vl in str(out).casefold():
            return "read-record"
    return "own/other"


def axor_gate(spec, ctx, cand):
    g = axor.governor(spec)
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
        if getattr(d, "grant_id", None) is not None:
            k = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
            if k is not None:
                g.grant_store.commit(k)
        if out is not None:
            axor_ajar.present(g, d, out, call.tool, dict(call.args))
    d = g.evaluate(cand.tool, axor_ajar.agent_args(g, dict(cand.args)))
    return bool(d.allowed), d.category


rows = []
for spec, probes in data:
    if str(spec.task) not in rope_only:
        continue
    req = [p for p in probes if p.scored and p.expected_label is Label.ALLOW and p.required]
    rres = {id(p): v for p, v in zip(req, [None] * len(req))}
    for p in req:
        rv = rope.decide(spec, p.context, p.candidate)
        av_allowed, av_gate = axor_gate(spec, p.context, p.candidate)
        if rv is Verdict.ALLOW and not av_allowed:
            # the call ROPE admits and axor denies
            legs = rope_leg(spec, p.context, p.candidate.tool, dict(p.candidate.args))
            origins = {a: value_origin(spec, p.context, (vv if not isinstance(vv, (list, tuple)) else (vv[0] if vv else "")))
                       for a, vv in dict(p.candidate.args).items()}
            rows.append({"task": str(spec.task), "tool": p.candidate.tool,
                         "args": {k: str(v)[:40] for k, v in dict(p.candidate.args).items()},
                         "rope_leg": legs, "axor_gate": av_gate, "value_origin": origins})

out = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
       "rope_router": "opus (cached)", "axor": "grants L1+L2s tuple, references on",
       "rope_provisioned": f"{len(rope_prov)}/52", "axor_provisioned": f"{len(axor_prov)}/52",
       "rope_only_tasks": rope_only, "n_rope_only": len(rope_only),
       "required_calls_rope_admits_axor_denies": rows}
op = os.path.join(HERE, "results", "rope_vs_axor_52_nsfix.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print("rope prov", len(rope_prov), "axor prov", len(axor_prov), "rope_only", len(rope_only))
for r in rows:
    print(" ", r["task"].split("/")[-1], r["tool"], "| rope_leg", r["rope_leg"], "| axor", r["axor_gate"], "| origin", r["value_origin"])
print("WROTE", op)
