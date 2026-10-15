"""MODEL.md §9.16/9.17, point 1: the 15 refused reference-plan calls whose value is only in text — the
read it comes from (tool, field, the record's sender), and why §9.13 did not apply."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import describe_bound as db  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import ContextRef  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, "results", "describe_bound_c9v3.json")))["rows"]
specs = {str(s.task): s for s, _ in run_ajar.load(None)}
out = []
for r in rows:
    for p in r["per_arg"]:
        if not str(p.get("reason", "")).startswith("only in"):
            continue
        spec = specs[r["task"]]
        cfg = axor_ajar.load_config(spec.task.suite, "context", "request-only")
        steps = axor_ajar.PREFIXES.outputs(spec, ContextRef(task=spec.task, prefix=tuple(range(len(spec.plan)))))
        outs = [(c.tool, dict(c.args), o) for c, o in steps[:r["step"]]]
        locs = []
        for tool, args, o in outs:
            if o is None or db.canon(p["value"]) not in db.canon(o):
                continue
            recs = db.records(o)
            hit = None
            for rec, _ in recs:
                for k, x in rec.items():
                    if isinstance(x, str) and db.canon(p["value"]) in db.canon(x):
                        hit = (k, rec.get("sender") or rec.get("from"), rec.get("recipient"))
            locs.append({"tool": tool, "args": args, "field": hit[0] if hit else "(whole text)",
                         "sender": hit[1] if hit else None, "recipient": hit[2] if hit else None})
        snd = next((l["sender"] for l in locs if l["sender"]), None)
        if snd is None:
            why = (f"no sender field: {locs[0]['tool']} is a document/web body"
                   if locs else "value in no read") + (" (no_sender_tools)" if locs and locs[0]["tool"] in
                                                         (cfg.no_sender_tools or ()) else "")
        else:
            why = f"sender {snd!r} is not named in the request (§9.13 needs the request to name it)"
            if not any(x in ("email", "iban", "url", "id") for x in [("url" if "." in str(p["value"]) else "")]):
                why += "; and the value is a user name (a string), not an identifier §9 extracts"
        out.append({"suite": r["suite"], "task": r["task"].split("/")[2].split("@")[0], "tool": r["tool"],
                    "arg": p["arg"], "value": p["value"], "reason": p["reason"], "reads": locs, "why_not_913": why,
                    "request": spec.prompt})
for x in out:
    l = x["reads"][0] if x["reads"] else {}
    print(f"| {x['suite']} | {x['task'].replace('user_task_', '')} | {x['tool']} | {x['arg']} | {x['value']} | "
          f"{l.get('tool')}({','.join(f'{k}={v}' for k, v in (l.get('args') or {}).items())}) field {l.get('field')}"
          f"{', sender ' + str(l.get('sender')) if l.get('sender') else ''} | {x['why_not_913']} |")
json.dump(out, open(os.path.join(HERE, "results", "hyp", "point1.json"), "w"), indent=1)
