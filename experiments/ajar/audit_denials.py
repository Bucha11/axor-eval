"""Denial audit on revision 4 (categories (a)-(e) as the user defined them).

(a) the value is only in an untrusted read, nowhere in the request;
(b) the value is in the request in some form, but the extractor/L1 did not admit it —
    with the rule that prevented it;
(c) the value is in the request but the call was denied by a taint match with a read;
(d) denied by consequence class / floor / access_control on a legitimate task;
(e) anything else.

Sources: Ajar's required calls (ALLOW-labelled probes) denied under (b) and (c)-oracle;
the recorded live v4/v5 calls re-decided by the revision-4 gate (replay_live.py, no
human). A call's class: (d) by its denial category first; otherwise from its relevant
values (grant args for a grant_gate denial, driving args for a taint denial): any value
only in a read -> (a); every value in the request -> (b) for grant_gate, (c) for taint;
else (e).

    AXOR_CORE_REPO=... AXOR_AJAR_CONFIG_DIR=.../config_rule python audit_denials.py <rl_v4_rev4.json> <rl_v5_rev4.json>
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import yaml  # noqa: E402

from axor_core.kernel.handles import canonicalize, split_kind  # noqa: E402
from axor_core.kernel.request_literals import is_request_fragment, is_typed_literal, literal_values  # noqa: E402

R0 = json.load(open(os.path.join(HERE, "live", "grant_args_R0.json")))
CFG = {s: yaml.safe_load(open(os.path.join(HERE, "config_rule", f"{s}.yaml")))
       for s in ("banking", "slack", "travel", "workspace")}


def norm(t):
    return re.sub(r"\s+", " ", str(t)).strip().casefold()


def strip_url(v):
    return re.sub(r"^[a-z][a-z0-9+.-]*://", "", norm(v)).rstrip("/")


def in_text(text, v):
    v = strip_url(v)
    if not v:
        return False
    t = norm(text).replace("\u2019", "'")
    v = v.replace("\u2019", "'")
    # a date-time is in the text "in some form" when its date and its clock time both are
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ t](\d{2}:\d{2})(?::\d{2})?", v)
    if m:
        hh = m.group(2).lstrip("0") or "0"
        return m.group(1) in t and (m.group(2) in t or re.search(r"(?<![\d:])" + re.escape(hh) + r"(:00)?\s*(am|pm)?", t) is not None)
    if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", t):
        return True
    # numbers in any form: 12 / 12.0 / 12.00
    try:
        x = float(v)
        return any(abs(float(n) - x) < 1e-9 for n in re.findall(r"\d+(?:\.\d+)?", t))
    except ValueError:
        return False


def leaves(v):
    if isinstance(v, (list, tuple)):
        return [x for x in v if x not in (None, "")]
    return [] if v in (None, "", {}) else [v]


def why_not_admitted(prompt, kind, v):
    s = str(v)
    if kind == "string":
        if is_typed_literal(s):
            return "type matching: a typed literal (file name / e-mail / date / number) in a string slot"
        if not is_request_fragment(prompt, s):
            return "string fragment: not a word-bounded fragment after normalization"
        return "L1 use already spent (quota 1 per value)"
    try:
        c = canonicalize(kind, s)
    except ValueError:
        return f"{kind}: the value does not parse as {kind}"
    lits = []
    for x in literal_values(prompt, kind):
        try:
            lits.append(canonicalize(kind, x))
        except ValueError:
            pass
    if c in lits:
        return "L1 use already spent (quota 1 per value)"
    if kind == "datetime":
        return "datetime: exact match — the request has no literal for this date-time (a date or a clock time alone does not cover it)"
    if kind == "id":
        return "id: only bare integers are id literals"
    return f"{kind}: the extractor found no {kind} literal for this value"


def classify(suite, tool, args, category, reason, prompt, reads):
    ac = set(CFG[suite].get("access_control_sinks") or [])
    if category == "consequence_gate" or "confidentiality" in (reason or "") or (category == "grant_gate" and tool in ac):
        return "d", None, []
    if category == "grant_gate":
        rel = {a: k for a, k in R0.get(suite, {}).get(tool, {}).items()}
    elif category == "taint_enforcement":
        rel = {a: "string" for a in (CFG[suite].get("driving_args", {}).get(tool) or [])}
    else:
        return "e", None, []
    vals = [(a, split_kind(rel[a])[0], x) for a in rel for x in leaves(args.get(a))]
    if not vals:
        return "e", None, []
    detail = []
    for a, k, x in vals:
        if in_text(prompt, x):
            src = "request"
        elif in_text(reads, x):
            src = "read only"
        else:
            src = "neither"
        detail.append({"arg": a, "kind": k, "value": x, "source": src})
    if any(d["source"] == "read only" for d in detail):
        return "a", None, detail
    if reads == "" and any(d["source"] == "neither" for d in detail):
        return "e", ["value not yet read at this decision point (no tool output before the call)"], detail
    if all(d["source"] == "request" for d in detail):
        if category == "grant_gate":
            rules = sorted({why_not_admitted(prompt, d["kind"], d["value"]) for d in detail})
            return "b", rules, detail
        return "c", None, detail
    return "e", None, detail


def ajar_rows():
    import axor_ajar
    import residuals as R
    import run_ajar
    from ajar.runner import run_defense
    from ajar.core.types import Label
    data = run_ajar.load(None)
    rows = []
    for name, d in (("b", axor_ajar.grants_defense("b", "L1+L2s", grant_args=R.r0())),
                    ("c-oracle", axor_ajar.grants_defense("c", "L1+L2s+L4", grant_args=R.r0(), confirm="oracle"))):
        for spec, probes in data:
            l0 = len(d.log)
            res = run_defense(d, spec, probes)
            log = d.log[l0:]
            for r, lg in zip(res, log):
                p = r.probe
                if p.expected_label is not Label.ALLOW or lg["allowed"]:
                    continue
                outs = axor_ajar.PREFIXES.outputs(spec, p.context)
                reads = "\n".join(o for _, o in outs if o)
                g = R.make_gov(spec, "b" if name == "b" else "c-oracle")
                # re-decide to get the reason text (the log keeps only the category)
                R_dec = R.run(spec, "b" if name == "b" else "c-oracle", len(p.context.prefix),
                              [(p.candidate.tool, dict(p.candidate.args), None)])
                cls, rules, det = classify(spec.task.suite, p.candidate.tool, dict(p.candidate.args),
                                           lg["category"], R_dec.reason, spec.prompt, reads)
                rows.append({"source": f"ajar-{name}", "suite": spec.task.suite, "task": str(spec.task),
                             "k": len(p.context.prefix), "tool": p.candidate.tool, "args": dict(p.candidate.args),
                             "category": lg["category"], "class": cls, "rules": rules, "values": det})
    return rows


def live_rows(path, label):
    rows = []
    for t in json.load(open(path)):
        for c in t["calls"]:
            if not c["allowed"]:
                cls, rules, det = classify(t["suite"], c["tool"], c["args"], c["category"], c["reason"],
                                           t["prompt"], c.get("reads_before", ""))
                rows.append({"source": label, "suite": t["suite"], "task": t["task"], "pass": t["pass"],
                             "tool": c["tool"], "args": c["args"], "category": c["category"], "class": cls,
                             "rules": rules, "values": det})
    return rows


def main(v4, v5):
    rows = ajar_rows()
    for p, lab in ((v4, "live-v4"), (v5, "live-v5")):
        rows += live_rows(p, lab)
    table = defaultdict(Counter)
    for r in rows:
        table[(r["source"], r["suite"])][r["class"]] += 1
    bc = [r for r in rows if r["class"] in ("b", "c")]
    random.seed(0)
    sample = random.sample(rows, min(20, len(rows)))
    rules = Counter(x for r in rows if r["class"] == "b" for x in (r["rules"] or []))
    out = {"table": {f"{s}|{u}": dict(c) for (s, u), c in sorted(table.items())},
           "b_rules": dict(rules.most_common()), "b_and_c": bc, "sample20": sample, "n": len(rows)}
    json.dump(out, open(os.path.join(HERE, "results", "audit_denials_rev4.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k in ("table", "b_rules", "n")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
