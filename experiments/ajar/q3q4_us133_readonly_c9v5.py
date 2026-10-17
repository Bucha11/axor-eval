"""Q3 + Q4, kernel 618c4a9 + config_m1_c9v5, config-grant path
(AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1, AXOR_AJAR_L2=tuple). NO model calls.

Q3  Why does banking OPL rise 0.060 -> 0.214 when US133 is added to the banking recipient
    operator set, at 0 admitted attacks? For every expected-DENY banking probe, decide it
    under grants L1+L2 with US133 OUT of O and with US133 IN O; list the probes that flip
    DENY->ALLOW. For each flip record: fault_class, required, harm_tier, penalty_weight,
    whether US133 is a substring of the request prompt (shown_raw/is_request), whether the
    probe's own prefix MINTS a reference for US133 (so agent_args would feed it as a handle),
    whether agent_args actually rewrites the candidate's US133 to a handle, the ALLOW
    category+grant_source (US133 in O) and the DENY category (US133 out of O).

Q4  Over Table 2 (all 97 tasks, L1+L2 config grant path, US133 OUT of O): among ADMITTED
    unneeded probes (required=False, expected ALLOW, verdict ALLOW), how many carry a driving
    value that the task exposes only through a read -- i.e. a string arg value (len>2) that is
    NOT a substring of the request prompt. Break those down by how the harness fed the value
    (raw vs handle) and by the admit category, to show whether the admit rode a raw literal
    that live (references on, value arriving as a handle) reference_origin would refuse.
"""
import os, sys, json, subprocess, dataclasses
from collections import Counter

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

import axor_ajar          # noqa: E402
import run_ajar           # noqa: E402
import paper_opl as P     # noqa: E402
from ajar.core.types import Label  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
US133 = "US133000000121212121212"

# ---- operator-set patch: add US133 to banking recipient O when ADD["on"] ----
_orig_load = axor_ajar.load_config
ADD = {"on": False}


def _patched(suite, integrity_default, integrity_origins):
    c = _orig_load(suite, integrity_default, integrity_origins)
    if ADD["on"] and suite == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    return c


axor_ajar.load_config = _patched

data = run_ajar.load(None)


def run_prefix(g, spec, ctx):
    """Replay a probe's prefix into governor g exactly as AxorDefense.decide does."""
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
        if getattr(d, "grant_id", None) is not None:
            k = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
            if k is not None:
                g.grant_store.commit(k)
        if out is not None:
            axor_ajar.present(g, d, out, call.tool, dict(call.args))


def decide_full(D, spec, probe):
    """Return (allowed, category, grant_source, fed_args, minted_values)."""
    g = D.governor(spec)
    run_prefix(g, spec, probe.context)
    minted = set()
    t = getattr(g, "_xrefs", None)
    if t is not None and t.by_name:
        minted = {str(r.value).casefold() for r in t.by_name.values()}
    fed = axor_ajar.agent_args(g, dict(probe.candidate.args))
    d = g.evaluate(probe.candidate.tool, fed)
    return (bool(d.allowed), d.category, getattr(d, "grant_source", None), fed, minted)


def str_vals(args):
    out = []
    def go(x):
        if isinstance(x, dict):
            for v in x.values():
                go(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                go(v)
        elif isinstance(x, str):
            out.append(x)
    go(args)
    return out


# =======================  Q3  =======================
D = P.make("grants:L1+L2s:R0")   # config-grant path via env; L2 tuple templates
bank = [(s, p) for s, p in data if s.task.suite == "banking"]

q3_flips = []
for spec, probes in bank:
    prompt_cf = (spec.prompt or "").casefold()
    deny = [p for p in probes if p.scored and p.expected_label is Label.DENY]
    for p in deny:
        if US133.casefold() not in str(dict(p.candidate.args)).casefold():
            continue  # OPL rise is specifically about US133 candidates
        ADD["on"] = False
        a_off, cat_off, gs_off, fed_off, minted_off = decide_full(D, spec, p)
        ADD["on"] = True
        a_on, cat_on, gs_on, fed_on, minted_on = decide_full(D, spec, p)
        if a_on and not a_off:  # flipped DENY -> ALLOW
            fed_has_handle = US133.casefold() not in str(fed_on).casefold()
            q3_flips.append({
                "task": str(spec.task),
                "tool": p.candidate.tool,
                "recipient": dict(p.candidate.args).get("recipient"),
                "args": {k: v for k, v in dict(p.candidate.args).items()},
                "fault_class": p.fault_class.value,
                "required": p.required,
                "harm_tier": p.harm_tier.name,
                "penalty_weight": p.penalty_weight,
                "us133_in_request": US133.casefold() in prompt_cf,
                "us133_minted_in_prefix": US133.casefold() in minted_on,
                "fed_as_handle": fed_has_handle,
                "deny_category_without_O": cat_off,
                "allow_category_with_O": cat_on,
                "allow_grant_source_with_O": gs_on,
                "prefix_k": len(p.context.prefix),
            })
ADD["on"] = False

# OPL for banking both ways + attacks (confirm 0), to tie flips to the 0.060->0.214 move
opl_off = P.measure(D, bank)
ADD["on"] = True
opl_on = P.measure(D, bank)
ADD["on"] = False
q3 = {
    "opl_banking_without_US133_in_O": {"opl": opl_off["opl"]["earliest"], "attacks": opl_off["attacks"]},
    "opl_banking_with_US133_in_O": {"opl": opl_on["opl"]["earliest"], "attacks": opl_on["attacks"]},
    "n_flipped_deny_to_allow": len(q3_flips),
    "flip_fault_classes": dict(Counter(f["fault_class"] for f in q3_flips)),
    "flip_required_false_count": sum(1 for f in q3_flips if not f["required"]),
    "flip_sum_penalty_weight": round(sum(f["penalty_weight"] for f in q3_flips), 3),
    "flips": q3_flips,
}

# =======================  Q4  =======================
# admitted unneeded probes carrying a read-only value (value not in request prompt)
ADD["on"] = False


def o_members(suite):
    """All operator-set literals for a suite (the configured known payees/channels/etc.)."""
    cfg = _orig_load(suite, "context", "request-only")
    s = set()
    for tool, args in cfg.operator_sets.items():
        for arg, vals in args.items():
            for v in vals:
                s.add(str(v).casefold())
    return s


O_BY_SUITE = {s: o_members(s) for s in {sp.task.suite for sp, _ in data}}


def driving_args(suite):
    cfg = _orig_load(suite, "context", "request-only")
    da = getattr(cfg, "driving_args", None) or {}
    return {t: set(a) for t, a in da.items()}


DA_BY_SUITE = {s: driving_args(s) for s in O_BY_SUITE}


def driving_str_vals(suite, tool, args):
    """String values (len>2) on the tool's configured DRIVING args only -- the args
    reference_origin / operator_set actually guard (recipient/iban/url/channel), not
    free-text content bodies."""
    keys = DA_BY_SUITE.get(suite, {}).get(tool, set())
    out = []
    for k in keys:
        v = args.get(k)
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            if isinstance(x, str) and len(x) > 2:
                out.append(x)
    return out

q4_rows = []
n_admitted_unneeded = 0
cat_breakdown = Counter()
readonly_cat = Counter()
readonly_fed = Counter()
ro_in_O = 0
ro_not_in_O_rawfed = 0   # the clean "harness fed raw; live untrusted handle would be refused" set
for spec, probes in data:
    prompt_cf = (spec.prompt or "").casefold()
    Oset = O_BY_SUITE[spec.task.suite]
    un = [p for p in probes if p.scored and p.expected_label is Label.ALLOW and not p.required]
    for p in un:
        allowed, cat, gs, fed, minted = decide_full(D, spec, p)
        if not allowed:
            continue
        n_admitted_unneeded += 1
        cat_breakdown[cat] += 1
        # DRIVING-arg string values not present in the request prompt (mirrors is_request)
        vals = driving_str_vals(spec.task.suite, p.candidate.tool, dict(p.candidate.args))
        ro = [v for v in vals if v.casefold() not in prompt_cf]
        if not ro:
            continue
        # for each read-only value: was it minted (fed as handle) or fed raw?
        fed_cf = str(fed).casefold()
        handle_fed = any(v.casefold() not in fed_cf for v in ro)  # some ro value replaced by a handle
        raw_fed = any(v.casefold() in fed_cf for v in ro)         # some ro value passed through raw
        readonly_cat[cat] += 1
        fedkind = "handle" if handle_fed and not raw_fed else ("raw" if raw_fed and not handle_fed else "mixed")
        readonly_fed[fedkind] += 1
        in_O = any(v.casefold() in Oset for v in ro)
        if in_O:
            ro_in_O += 1
        elif raw_fed:
            ro_not_in_O_rawfed += 1
        q4_rows.append({
            "task": str(spec.task), "suite": spec.task.suite, "tool": p.candidate.tool,
            "fault_class": p.fault_class.value, "readonly_values": ro[:4],
            "admit_category": cat, "grant_source": gs,
            "fed_as_handle": handle_fed, "fed_raw": raw_fed, "readonly_value_in_O": in_O,
            "value_minted_in_prefix": any(v.casefold() in minted for v in ro),
        })

q4 = {
    "admitted_unneeded_total": n_admitted_unneeded,
    "admitted_unneeded_category_breakdown": dict(cat_breakdown),
    "admitted_unneeded_with_readonly_value": len(q4_rows),
    "readonly_admit_category_breakdown": dict(readonly_cat),
    "readonly_fed_breakdown": dict(readonly_fed),
    "readonly_minted_in_prefix_count": sum(1 for r in q4_rows if r["value_minted_in_prefix"]),
    "readonly_value_in_operator_set": ro_in_O,
    "readonly_value_not_in_O_and_fed_raw": ro_not_in_O_rawfed,
    "examples": q4_rows[:30],
}

out = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
       "grant_path": "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 + AXOR_AJAR_L2=tuple",
       "Q3_us133_opl_rise": q3, "Q4_readonly_admitted_unneeded": q4}
op = os.path.join(HERE, "results", "q3q4_us133_readonly_c9v5.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print("Q3 flips:", q3["n_flipped_deny_to_allow"], "fault_classes", q3["flip_fault_classes"],
      "sum_w", q3["flip_sum_penalty_weight"])
print("Q3 opl", q3["opl_banking_without_US133_in_O"], "->", q3["opl_banking_with_US133_in_O"])
print("Q4 admitted_unneeded", q4["admitted_unneeded_total"],
      "with_readonly", q4["admitted_unneeded_with_readonly_value"])
print("Q4 readonly cat", q4["readonly_admit_category_breakdown"], "fed", q4["readonly_fed_breakdown"])
print("WROTE", op)
