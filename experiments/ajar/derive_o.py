"""Revision 7: the operator set O per suite from the initial environment, the check
O ∩ attacker entities, and config_rule_o/ (= config_rule + operator_trusted: O).

    python derive_o.py            -> results/operator_o.json, config_rule_o/*.yaml
"""
from __future__ import annotations

import json
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ("banking", "slack", "travel", "workspace")
TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|(?:https?://|www\.)\S+")


def derive(name, env):
    if name == "banking":
        ba = env.bank_account
        o = {t.recipient for t in ba.transactions if t.sender in ("me", ba.iban)}
        o |= {t.recipient for t in ba.scheduled_transactions}
        return {"known payees": sorted(o)}
    if name == "slack":
        return {"users": sorted(env.slack.users),
                "channels": sorted(c for c in env.slack.channels if not c.startswith("External_"))}
    if name == "workspace":
        me = env.inbox.account_email
        dom = "@" + me.split("@", 1)[1]
        addrs = set()
        for m in env.inbox.emails.values():
            addrs |= {m.sender, *m.recipients, *m.cc, *m.bcc}
        for f in env.cloud_drive.files.values():
            addrs |= {f.owner, *f.shared_with}
        for e in env.calendar.events.values():
            addrs |= set(e.participants)
        org = sorted(a for a in addrs if a.endswith(dom))
        files = sorted((f.id_ for f in env.cloud_drive.files.values() if f.owner == me), key=int)
        parts = sorted({p for e in env.calendar.events.values() if me in e.participants for p in e.participants})
        return {"organisation addresses": org, "own files": files, "own-event participants": parts}
    return {}


def _leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _leaves(v)
    elif isinstance(x, (list, tuple, set)):
        for v in x:
            yield from _leaves(v)
    elif isinstance(x, str):
        yield x


def attacker_entities(suite, env):
    out = {}
    for it_id, it in suite.injection_tasks.items():
        vals = set(_leaves([c.args for c in it.ground_truth(env)]))
        vals |= {t.rstrip(".,;:!?)'\"") for t in TOKEN.findall(it.GOAL)}
        out[it_id] = vals
    return out


def main():
    from agentdojo.task_suite.load_suites import get_suite
    res = {}
    os.makedirs(os.path.join(HERE, "config_rule_o"), exist_ok=True)
    for name in SUITES:
        suite = get_suite("v1", name)
        env = suite.load_and_inject_default_environment({})
        parts = derive(name, env)
        o = sorted({v for vs in parts.values() for v in vs})
        att = attacker_entities(suite, env)
        cf = lambda s: s.casefold()
        hits = {it: sorted(v for v in vals if cf(v) in {cf(x) for x in o}) for it, vals in att.items()}
        hits = {k: v for k, v in hits.items() if v}
        res[name] = {"O": parts, "size": len(o), "intersection": hits}
        cfg = yaml.safe_load(open(os.path.join(HERE, "config_rule", f"{name}.yaml")))
        cfg["operator_trusted"] = o
        with open(os.path.join(HERE, "config_rule_o", f"{name}.yaml"), "w") as fh:
            fh.write(f"# config_rule/{name}.yaml + operator_trusted: O (residuals_rules.md revision 7,\n"
                     "# derive_o.py). Do not edit by hand.\n")
            yaml.safe_dump(cfg, fh, sort_keys=False)
    json.dump(res, open(os.path.join(HERE, "results", "operator_o.json"), "w"), indent=1)
    for name, r in res.items():
        print(f"\n== {name}: |O| = {r['size']}")
        for k, v in r["O"].items():
            print(f"   {k} ({len(v)}): {v}")
        print(f"   O ∩ attacker entities: {r['intersection'] or 'empty'}")


if __name__ == "__main__":
    main()
