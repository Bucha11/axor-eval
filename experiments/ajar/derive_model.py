"""Config from two models (MODEL.md): the tool model (model/tools.yaml) and the entity model
(the suite's initial state), compiled by fixed rules into the kernel's current config format.

    python derive_model.py [--m1 [--content]]
        default -> config_model/   (M0)
        --m1    -> config_m1/      (MODEL.md §8: consequence per call, magnitude limits)
        --m1 --content -> config_m1_content/ (+ content projection, §8.4)

The content role (MODEL.md §5) is not compiled: it needs sub-field extraction the gate does not
do (paper §5.6); its cost is measured offline (content_role_cost.py). Run in the Ajar venv.
"""
from __future__ import annotations

import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from derive_grants import is_rich  # noqa: E402

SUITES = ("banking", "slack", "travel", "workspace")
CLASS = {"read": "benign", "write_own": "reversible", "send": "consequential", "share": "consequential",
         "invite": "consequential", "pay": "consequential", "reserve": "consequential",
         "fetch": "consequential", "delete": "catastrophic", "credential": "catastrophic"}
DEST = {"recipient", "recipients", "cc", "bcc", "participants", "email", "user_email", "user", "channel", "url"}
MAGNITUDE = re.compile(r"^amount$")  # §8.6: dates and times are role "other"
EMAIL_ARGS = {"recipients", "cc", "bcc", "participants", "email", "user_email"}
TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|(?:https?://|www\.)\S+")


def role(arg, prop, override):
    if arg in override:
        return override[arg]
    if is_rich(arg, prop):
        return "content"
    if arg in DEST:
        return "destination"
    if arg == "id" or arg.endswith("_id"):
        return "object"
    if MAGNITUDE.search(arg):
        return "magnitude"
    return "other"


# ── entity model (MODEL.md §1): own entities and who sees what, from the initial state ──
def entities(name, env):
    own, ids, viewers = {}, [], {}
    if name == "banking":
        ba = env.bank_account
        own["payee"] = sorted({t.recipient for t in ba.transactions if t.sender in ("me", ba.iban)}
                              | {t.recipient for t in ba.scheduled_transactions})
        ids = [ba.iban]
    elif name == "slack":
        own["slack_user"] = sorted(env.slack.users)
        own["channel"] = sorted(c for c in env.slack.channels if not c.startswith("External_"))
    elif name == "workspace":
        me = env.inbox.account_email
        dom = "@" + me.split("@", 1)[1]
        addrs = set()
        for m in env.inbox.emails.values():
            addrs |= {m.sender, *m.recipients, *m.cc, *m.bcc}
        for f in env.cloud_drive.files.values():
            addrs |= {f.owner, *f.shared_with}
        for e in env.calendar.events.values():
            addrs |= set(e.participants)
        own["address"] = sorted({a for a in addrs if a.endswith(dom)}
                                | {p for e in env.calendar.events.values() if me in e.participants
                                   for p in e.participants})
        own["file"] = sorted((f.id_ for f in env.cloud_drive.files.values() if f.owner == me), key=int)
        own["event"] = sorted((e.id_ for e in env.calendar.events.values() if me in e.participants), key=int)
        own["email"] = sorted((m.id_ for m in env.inbox.emails.values() if m.sender == me), key=int)
        ids = [me]
        viewers["file_id"] = {f.id_: list(f.shared_with) for f in env.cloud_drive.files.values() if f.shared_with}
        viewers["event_id"] = {e.id_: [p for p in e.participants if p != me]
                               for e in env.calendar.events.values() if len(e.participants) > 1}
    elif name == "travel":
        ids = [env.user.email]
        own["event"] = sorted((e.id_ for e in env.calendar.events.values()
                               if env.user.email in e.participants), key=int)
        viewers["event_id"] = {e.id_: [p for p in e.participants if p != env.user.email]
                               for e in env.calendar.events.values() if len(e.participants) > 1}
    return own, ids, viewers


def entity_class(suite, tool, arg, rl):
    """Which own-entity class a destination/object argument draws from (by suite and kind)."""
    if suite == "banking" and arg == "recipient":
        return "payee"
    if suite == "slack" and arg in ("recipient", "user") and tool != "invite_user_to_slack":
        return "slack_user"   # inviting creates a new member: not an own entity
    if suite == "slack" and arg == "channel":
        return "channel"
    if suite == "workspace" and arg in EMAIL_ARGS:
        return "address"
    if suite == "workspace" and arg == "file_id":
        return "file"
    if suite in ("workspace", "travel") and arg == "event_id":
        return "event"
    if suite == "workspace" and arg == "email_id":
        return "email"
    return None


def leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from leaves(v)
    elif isinstance(x, (list, tuple, set)):
        for v in x:
            yield from leaves(v)
    elif isinstance(x, str):
        yield x


def main():
    from agentdojo.task_suite.load_suites import get_suite
    model = yaml.safe_load(open(os.path.join(HERE, "model", "tools.yaml")))
    m1 = "--m1" in sys.argv
    content_opt = m1 and "--content" in sys.argv
    out_dir = os.path.join(HERE, "config_m1_content" if content_opt else "config_m1" if m1 else "config_model")
    os.makedirs(out_dir, exist_ok=True)
    report = {}
    for s in SUITES:
        suite = get_suite("v1", s)
        env = suite.load_and_inject_default_environment({})
        tm = model[s]
        tools = {f.name: f for f in suite.tools}
        effects = tm["effects"]
        over = tm.get("roles") or {}
        roles = {}
        for t in effects:
            props = tools[t].parameters.model_json_schema().get("properties", {})
            roles[t] = {a: role(a, p, over.get(t, {})) for a, p in props.items()}
        own, ids, viewers = entities(s, env)
        bound = None
        if s == "banking":  # §8.1: the largest amount the user has sent
            ba = env.bank_account
            bound = max([t.amount for t in ba.transactions if t.sender in ("me", ba.iban)]
                        + [t.amount for t in ba.scheduled_transactions])
        audience = sorted({v for vs in own.values() for v in vs} | set(ids))
        aud = {a.casefold() for a in audience}

        # MODEL.md §1.3: no own entity / viewer may be an attacker entity
        att = {}
        for it_id, it in suite.injection_tasks.items():
            vals = set(leaves([c.args for c in it.ground_truth(env)]))
            vals |= {x.rstrip(".,;:!?)'\"") for x in TOKEN.findall(it.GOAL)}
            att[it_id] = {v.casefold() for v in vals}
        # attacker-CONTROLLED = identifiers the injection goal brings in (its e-mail, IBAN, URL,
        # a user it invites); attacker-TARGETED = own entities it aims at (a member it messages)
        ctrl = {}
        for it_id, it in suite.injection_tasks.items():
            c = {x.rstrip(".,;:!?)'\"").casefold() for x in TOKEN.findall(it.GOAL)}
            for call in it.ground_truth(env):
                if call.function == "invite_user_to_slack":
                    c |= {str(v).casefold() for v in call.args.values()}
            ctrl[it_id] = c
        hits = {}
        for it_id, vals in att.items():
            h = sorted(a for a in audience if a.casefold() in vals)
            if h:
                hits[it_id] = {"controlled": [a for a in h if a.casefold() in ctrl[it_id]],
                               "targeted": [a for a in h if a.casefold() not in ctrl[it_id]]}

        # a read: every tool that is not a sink, plus a sink that also returns content
        # (get_unread_emails reads mail and marks it read)
        reads = [t for t in tools if t not in effects or t.startswith("get_")]
        cfg = {
            "mode": "production",
            "untrusted_sources": sorted(reads + [t for t in ("get_webpage",) if t in tools]),
            "sensitive_sources": sorted(t for t in reads if t not in tm.get("public", [])),
            "egress_sinks": sorted(t for t in effects if any(r == "destination" for r in roles[t].values())),
            "integrity_sinks": sorted(t for t in effects if not any(r == "destination" for r in roles[t].values())),
            "access_control_sinks": sorted(t for t, e in effects.items() if e == "credential"),
            "driving_args": {t: sorted(a for a, r in roles[t].items()
                                       if r != "content" and (not m1 or r in ("destination", "object", "magnitude")))
                             for t in sorted(effects)},
            "consequence_overrides": {**{t: "benign" for t in sorted(reads) if t not in effects},
                                      **{t: CLASS[e] for t, e in sorted(effects.items())}},
            "max_unattended_consequence": "reversible",
            "operator_sets": {},
            "operator_sets_refuse_above": "benign",
            "floor_scope": "all_mutating",
            "floor_mode": "audience",
            "audience": audience,
            "destination_args": {t: sorted(a for a, r in roles[t].items() if r == "destination")
                                 for t in sorted(effects) if any(r == "destination" for r in roles[t].values())},
            "content_args": {t: sorted(a for a, r in roles[t].items() if r == "content") for t in sorted(effects)},
            "shared_stores": {},
        }
        if not m1:
            cfg["driving_args"] = {t: a for t, a in cfg["driving_args"].items() if a}
        cfg["sensitive_sources"] = sorted(set(cfg["sensitive_sources"]))
        for t in sorted(effects):
            for a, r in roles[t].items():
                if r in ("destination", "object"):
                    # rule 3.2: own or named — with no own class of that kind, an empty set
                    # (only what the request names)
                    k = entity_class(s, t, a, r)
                    cfg["operator_sets"].setdefault(t, {})[a] = own.get(k, []) if k else []
        # shared stores (MODEL.md §3.3): an object argument whose object is seen by someone
        # outside the audience
        for t in sorted(effects):
            for a, r in roles[t].items():
                if r == "object" and a in viewers:
                    held = sorted((i for i, ppl in viewers[a].items()
                                   if any(p.casefold() not in aud for p in ppl)), key=lambda x: int(x))
                    if held:
                        cfg["shared_stores"].setdefault(t, {})[a] = held
        if m1:
            # §8.1 κ = effect × target × magnitude: overrides carry the external class, rules
            # lower it for an own-targeted call or raise it above the magnitude bound
            ext = {"write_own": "consequential"}
            for t, e in effects.items():
                cfg["consequence_overrides"][t] = ext.get(e, CLASS[e])
            rules = {}
            for t, e in sorted(effects.items()):
                if e in ("write_own", "send", "share", "fetch"):
                    rules[t] = {"own": "reversible"}
                if e == "pay" and bound is not None:
                    rules[t] = {"magnitude": {"arg": "amount", "above": bound, "class": "catastrophic"}}
            cfg["consequence_rules"] = rules
            # §8.3: amount <= bound as a template component on the payment sinks
            if bound is not None:
                cfg["template_limits"] = {t: {"amount": bound} for t, e in effects.items()
                                          if e == "pay" and "amount" in roles[t]}
            cfg["operator_sets_confirm"] = True  # §8.5
            cfg["absent_driving_is_empty"] = True  # §8.8
            # §8.7: grant arguments = driving arguments (kinds from the schema table R0);
            # unlimited quota on tools whose own-targeted class is REVERSIBLE
            r0 = json.load(open(os.path.join(HERE, "live", "grant_args_R0.json")))[s]
            def kind(t, a):
                if a in (r0.get(t) or {}):
                    return r0[t][a]
                return {"amount": "money", "url": "url"}.get(a, "id" if a.endswith("_id") or a == "id"
                                                             else "email" if a in EMAIL_ARGS else "string")
            cfg["grant_args"] = {t: {a: kind(t, a) for a in d} for t, d in cfg["driving_args"].items() if d}
            cfg["grant_quotas"] = {t: None for t, e in effects.items()
                                   if e in ("write_own", "send", "share") and t in cfg["grant_args"]}
            if content_opt:
                cfg["content_projection"] = True
        for k in ("access_control_sinks", "operator_sets", "shared_stores"):
            if not cfg[k]:
                cfg.pop(k)
        with open(os.path.join(out_dir, f"{s}.yaml"), "w") as fh:
            fh.write(f"# Generated by derive_model.py from model/tools.yaml and the initial state of {s}\n"
                     "# (MODEL.md). Do not edit by hand.\n")
            yaml.safe_dump(cfg, fh, sort_keys=False)
        report[s] = {"roles": roles, "own": own, "user_ids": ids, "attacker_hits": hits}
        print(f"== {s}: own {{{', '.join(f'{k}:{len(v)}' for k, v in own.items())}}}  attacker ∩ own/audience: {hits or 'empty'}")
    if not m1:
        json.dump(report, open(os.path.join(HERE, "results", "model_report.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
