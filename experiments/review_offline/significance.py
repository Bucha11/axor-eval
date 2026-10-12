"""Where the consumption behaviours sit: sink tools, driving fields, and whether
any lets a value a check approved produce a larger effect.

AgentDojo: sinks and driving fields as the STRICT configs declare them.
LangChain community: sink tools and driving fields by name (verbs such as send,
post, write, delete, execute; fields such as to, recipient, url, path, id) — a
heuristic, stated as such.

Run (AgentDojo):  uv run --no-project --with agentdojo==0.1.35 --with pyyaml \
                    --with-editable ../../../axor-core python significance.py agentdojo
Run (LangChain):  uv run --no-project --with langchain-community --with pyyaml \
                    --with-editable ../../../axor-core python significance.py langchain
"""
from __future__ import annotations

import collections
import os
import re
import sys

SINK = re.compile(r"(Send|Post|Write|Delete|Create|Move|Copy|Execute|Run|Shell|Request|Update|Upload|"
                  r"Publish|Reply|Schedule|Comment|Submit|Put|Patch|Transfer|Pay|Invite|Add|Remove|"
                  r"Set|Replace|Append|Close|Merge|Push|Draft|Tweet|Message|Email)", re.I)
DRV = re.compile(r"(^to$|recipient|email|url|uri|path|dest|channel|repo|file|address|phone|number|"
                 r"account|user|id$|_id$|query|command|commands|code|sql|host|target)", re.I)


def agentdojo(core="../../../axor-core"):
    import yaml
    import contract_audit as A
    rows = A.audit()
    drv, sinks = {}, set()
    for n in ("banking", "slack", "travel", "workspace"):
        cfg = yaml.safe_load(open(os.path.join(core, f"examples/agentdojo/config/{n}_strict.yaml")))
        sinks |= set(cfg.get("egress_sinks", [])) | set(cfg.get("integrity_sinks", []))
        for s, a in cfg["driving_args"].items():
            drv.setdefault(s, set()).update(a)
    on_sink = [r for r in rows if r[1] in sinks]
    on_drv = [r for r in rows if r[2] in drv.get(r[1], set())]
    return {"parameters": len(rows), "on_sinks": len(on_sink), "driving": len(on_drv),
            "hidden_on_driving": [(r[1], r[2], r[3]) for r in on_drv if r[3]]}


def langchain():
    import contract_audit_heldout as H
    rows = H.audit()
    sink_rows = [r for r in rows if SINK.search(r[0].split(".")[-1])]
    drv_rows = [r for r in sink_rows if DRV.search(r[1])]
    return {"tools_with_run": len(H._tools()), "audited_tools": len({r[0] for r in rows}),
            "parameters": len(rows), "on_sink_tools": len(sink_rows), "driving_named": len(drv_rows),
            "hidden_on_driving": [(r[0].split(".", 2)[-1], r[1], r[2]) for r in drv_rows if r[2]]}


if __name__ == "__main__":  # pragma: no cover
    print((agentdojo if sys.argv[1:] == ["agentdojo"] else langchain)())
