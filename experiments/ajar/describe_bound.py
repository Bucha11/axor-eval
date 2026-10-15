"""Bound on the gain from description grants (counting only; no kernel code).

For every reference-plan call of the Ajar AgentDojo tasks (all 4 suites) that the current
configuration refuses without a human (mode b, grants without L4), decide whether its target /
object is computable from STRUCTURED fields of earlier reads (fields the platform sets: numbers,
sender / recipients, membership lists, ids of a structured list) and, if so, write the description
form in one line with where its parameters come from (request literal / own). Otherwise the reason:
only in free text (a page, a file body), only in the text of a message from an unnamed sender, or
other (not in any read).

Then the attack side: Ajar attacker-seeded probes and recorded replay runs whose sink call has the
same form (same task, same sink and argument) but a different value — a description would refuse it.

    AXOR_AJAR_CONFIG_DIR=config_m1_c9v3 AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 \
    AXOR_CORE_REPO=... python describe_bound.py OUT.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import paper_opl  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import ContextRef, Verdict  # noqa: E402

TEXT_FIELDS = {"body", "content", "description", "text", "message", "summary", "reviews", "subject", "title",
               "note", "notes"}
SENDER_FIELDS = {"sender", "from"}
NUM = (int, float)


def canon(v):
    v = str(v).strip().casefold()
    v = re.sub(r"^https?://", "", v)
    return re.sub(r"^www\.", "", v).rstrip("/")


def records(out):
    """[(record dict, list it belongs to | None)] from a YAML tool output; [] if not structured."""
    try:
        y = yaml.safe_load(out)
    except Exception:
        return []
    if isinstance(y, dict):
        # a dict of records keyed by name (e.g. {hotel: 'Rating: ...'}) is text per key
        if all(not isinstance(v, (dict, list)) for v in y.values()) and not any(k in y for k in ("id", "id_")):
            return [({"__key__": k, "__text__": v}, None) for k, v in y.items()]
        return [(y, None)]
    if isinstance(y, list) and y and all(isinstance(x, dict) for x in y):
        return [(x, y) for x in y]
    if isinstance(y, list) and y and all(isinstance(x, (str, int)) for x in y):
        # a structured list of names / ids (channels, users): one pseudo-record per element
        return [({"__element__": x}, y) for x in y]
    return []


def where(value, outs):
    """Where a value sits in earlier outputs: [(kind, info)]: kind in structured / text / sender_text."""
    v = canon(value)
    found = []
    for tool, args, out in outs:
        if out is None:
            continue
        recs = records(out)
        if not recs:
            if v and v in canon(out):
                found.append(("text", {"tool": tool}))
            continue
        for rec, lst in recs:
            for k, x in rec.items():
                xs = x if isinstance(x, list) else [x]
                for y in xs:
                    if isinstance(y, (dict, list)):
                        continue
                    cy = canon(y)
                    if cy == v and k not in TEXT_FIELDS and k != "__text__":  # incl. __element__
                        found.append(("structured", {"tool": tool, "args": args, "field": k, "rec": rec, "list": lst}))
                    elif v and v in cy and (k in TEXT_FIELDS or k == "__text__"):
                        snd = next((rec[f] for f in SENDER_FIELDS if f in rec), None)
                        found.append(("sender_text" if snd else "text", {"tool": tool, "sender": snd}))
    return found


def element_selector(info, prompt, outs):
    """For an element of a structured list: chosen by a request fragment, or by the fewest / most
    records another read returns for it (e.g. read_channel_messages(channel=e))."""
    lst, tool = info["list"], info["tool"]
    e = info["rec"]["__element__"]
    words = [w for w in re.findall(r"[\w'-]{3,}", prompt) if w.casefold() not in {"the", "and", "with", "that", "channel", "user", "users"}]
    hits = [w for w in words if w.casefold() in str(e).casefold()]
    if hits and sum(1 for x in lst if any(w.casefold() in str(x).casefold() for w in hits)) == 1:
        return f"element of {tool}() containing <request fragment '{hits[0]}'>", "request"
    counts = {}
    for t, a, o in outs:
        for x in lst:
            if x in (a or {}).values():
                rs = records(o) if o else []
                counts[x] = len(rs)
    if len(counts) == len(lst) and len(lst) >= 2:
        for name, f in (("fewest", min), ("most", max)):
            m = f(counts.values())
            if counts.get(e) == m and list(counts.values()).count(m) == 1:
                return f"element of {tool}() with the {name} records in the read keyed by it", "structured"
    if len(lst) == 1:
        return f"the only element of {tool}()", "structured"
    return None


def selector(info, prompt, own, outs=()):
    """A description of the record holding the value, or None."""
    if "__element__" in info["rec"]:
        r = element_selector(info, prompt, outs)
        return r if r else (None, None)
    rec, lst, tool, args = info["rec"], info["list"], info["tool"], info["args"]
    p = prompt.casefold()
    src = "request" if all(canon(a) in canon(prompt) for a in (args or {}).values() if isinstance(a, str) and a) else "own/none"
    targs = ", ".join(f"{k}" for k in (args or {}))
    head = f"{info['field']} of the record in {tool}({targs})"
    # a) a field of the record equals a request literal (title, subject, name, …)
    for k, x in rec.items():
        if k in (info["field"],) or isinstance(x, (dict, list, bool)) or x is None:
            continue
        sx = str(x).strip()
        if len(sx) >= 3 and sx.casefold() in p:
            return f"{head} with {k} = <request literal>", "request"
    # b) the only record of the list (or a single record)
    if lst is None or len(lst) == 1:
        return f"{head} (the only record)", src
    # c) argmax / argmin of a numeric field
    for k, x in rec.items():
        if isinstance(x, NUM) and not isinstance(x, bool):
            vals = [r.get(k) for r in lst if isinstance(r.get(k), NUM)]
            if len(vals) >= 2 and x == max(vals) and vals.count(x) == 1:
                return f"{head} with the largest {k}", src
            if len(vals) >= 2 and x == min(vals) and vals.count(x) == 1:
                return f"{head} with the smallest {k}", src
    # d) a field of the record is own
    for k, x in rec.items():
        if not isinstance(x, (dict, list)) and str(x).casefold() in own:
            return f"{head} with {k} = <own>", "own"
    return None, None


def main(out_path):
    d = paper_opl.make("grants:L1+L2s:R0")
    rows = []
    for spec, probes in run_ajar.load(None):
        cfg = axor_ajar.load_config(spec.task.suite, "context", "request-only")
        own = {str(x).casefold() for x in cfg.audience}
        driving = {t: list(v) for t, v in cfg.driving_args.items()}
        full = ContextRef(task=spec.task, prefix=tuple(range(len(spec.plan))))
        steps = axor_ajar.PREFIXES.outputs(spec, full)
        for i, (call, _out) in enumerate(steps):
            if call.tool not in driving and call.tool not in cfg.egress_sinks | cfg.integrity_sinks:
                continue
            v = d.decide(spec, ContextRef(task=spec.task, prefix=tuple(range(i))), call)
            if v is Verdict.ALLOW:
                continue
            outs = [(c.tool, dict(c.args), o) for c, o in steps[:i]]
            args = dict(call.args)
            per_arg = []
            category = d.log[-1]["category"] if d.log else ""
            targets = [a for a in (driving.get(call.tool) or []) if not re.search(r"amount|date|time|day", a)]
            passed = [a for a in targets if args.get(a) not in (None, "", [], {})]
            if not passed:
                rows.append({"suite": spec.task.suite, "task": str(spec.task), "step": i, "tool": call.tool,
                             "args": {}, "closed": False, "kind": "no target in the call", "category": category,
                             "per_arg": []})
                continue
            for a in passed:
                val = args.get(a)
                vals = val if isinstance(val, list) else [val]
                for x in vals:
                    if x in (None, "") or isinstance(x, bool):
                        continue
                    if canon(x) in canon(spec.prompt) or canon(x) in own:
                        per_arg.append({"arg": a, "value": x, "status": "R/own"})
                        continue
                    locs = where(x, outs)
                    st = [l for l in locs if l[0] == "structured"]
                    if st:
                        form, src = selector(st[0][1], spec.prompt, own, outs)
                        if form:
                            per_arg.append({"arg": a, "value": x, "status": "described", "form": form, "params": src})
                            continue
                        per_arg.append({"arg": a, "value": x, "status": "structured, no selector",
                                        "field": st[0][1]["field"], "tool": st[0][1]["tool"]})
                        continue
                    kinds = {l[0] for l in locs}
                    reason = ("only in the text of a message from an unnamed sender" if "sender_text" in kinds
                              else "only in free text (page / file / body)" if "text" in kinds
                              else "other (not in any read)")
                    per_arg.append({"arg": a, "value": x, "status": "not described", "reason": reason})
            if all(p["status"] == "R/own" for p in per_arg):
                kind = "target proven; refused for another reason"
            elif all(p["status"] in ("described", "R/own") for p in per_arg):
                kind = "target closable by a description"
            else:
                kind = "target not describable"
            closed = kind == "target closable by a description"
            rows.append({"suite": spec.task.suite, "task": str(spec.task), "step": i, "tool": call.tool,
                         "args": {k: args[k] for k in passed}, "closed": closed, "kind": kind,
                         "category": category, "per_arg": per_arg})
            print(rows[-1]["task"].split("/")[1], rows[-1]["task"].split("/")[2][:16], call.tool, closed,
                  [(p["arg"], p["status"], p.get("form") or p.get("reason") or "") for p in per_arg], flush=True)
    # summary
    summ = {}
    for s in ("banking", "slack", "travel", "workspace", "all"):
        rs = [r for r in rows if s == "all" or r["suite"] == s]
        tasks = defaultdict(list)
        for r in rs:
            tasks[r["task"]].append(r["closed"])
        tgt = [r for r in rs if r["kind"] in ("target closable by a description", "target not describable")]
        ttasks = defaultdict(list)
        for r in rs:
            ttasks[r["task"]].append(r["kind"])
        summ[s] = {"refused_calls": len(rs),
                   "by_kind": dict(Counter(r["kind"] for r in rs)),
                   "target_refusals": len(tgt), "closable": sum(r["closed"] for r in tgt),
                   "tasks_with_refusal": len(ttasks),
                   "tasks_all_refusals_closable": sum(all(k == "target closable by a description" for k in v)
                                                      for v in ttasks.values())}
    forms = Counter(p["form"] for r in rows for p in r["per_arg"] if p["status"] == "described")
    reasons = Counter(p.get("reason") or p["status"] for r in rows for p in r["per_arg"]
                      if p["status"] not in ("described", "R/own"))
    # attack side: same task, same sink + argument as a described call, a different value
    described = {(r["task"], r["tool"], p["arg"]): str(p["value"]) for r in rows for p in r["per_arg"]
                 if p["status"] == "described"}
    atk = Counter()
    atk_ids = set()
    for spec, probes in run_ajar.load(None):
        for p in probes:
            if p.fault_class.value != "ATTACKER_SEEDED":
                continue
            c = p.candidate
            for a, x in dict(c.args).items():
                key = (str(spec.task), c.tool, a)
                if key in described and canon(x) != canon(described[key]):
                    atk["probes"] += 1
                    atk_ids.add((str(spec.task), p.ground_truth.get("injection_id")))
    res = {"summary": summ, "forms": forms.most_common(), "not_described": reasons.most_common(),
           "ajar_attack_probes_same_form_other_value": atk["probes"],
           "ajar_attacks_same_form_other_value": len(atk_ids), "rows": rows}
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    json.dump(res, open(out_path, "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
