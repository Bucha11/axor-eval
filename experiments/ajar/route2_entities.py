"""Route 2 (final config) re-read from saved data: a candidate counts only if its value is an
existing entity of its kind in the suite's initial state (an executable call). Per ground
source (L1 request / L2 own): admitted, k (median / p90 / max). No new run.

    python route2_entities.py   (Ajar venv)  -> results/route2_entities.json
"""
import collections
import gzip
import json
import os
import re
import statistics

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def canon(v):
    v = str(v).strip().casefold()
    v = re.sub(r"^https?://", "", v)
    return re.sub(r"^www\.", "", v).rstrip("/")


def entities(suite, env):
    """kind -> set of canonical existing values (initial state, structured fields)."""
    e = collections.defaultdict(set)
    if suite == "travel":
        e["hotel"] = {canon(h.name) for h in env.hotels.hotel_list}
        e["restaurant"] = {canon(r.name) for r in env.restaurants.restaurant_list}
        e["company"] = {canon(c.name) for c in env.car_rental.company_list}
        e["event_id"] = {canon(i) for i in env.calendar.events}
        addrs = {env.user.email} | {p for ev in env.calendar.events.values() for p in ev.participants}
        for m in env.inbox.emails.values():
            addrs |= {m.sender, *m.recipients, *m.cc, *m.bcc}
        e["email"] = {canon(a) for a in addrs}
    elif suite == "slack":
        e["user"] = {canon(u) for u in env.slack.users}
        e["channel"] = {canon(c) for c in env.slack.channels}
        e["url"] = {canon(u) for u in env.web.web_content}
    elif suite == "workspace":
        addrs = {env.inbox.account_email}
        for m in env.inbox.emails.values():
            addrs |= {m.sender, *m.recipients, *m.cc, *m.bcc}
        for f in env.cloud_drive.files.values():
            addrs |= {f.owner, *f.shared_with}
        for ev in env.calendar.events.values():
            addrs |= set(ev.participants)
        addrs |= {c.email for c in env.inbox.contact_list}
        e["email"] = {canon(a) for a in addrs}
        e["file_id"] = {canon(i) for i in env.cloud_drive.files}
        e["event_id"] = {canon(i) for i in env.calendar.events}
        e["email_id"] = {canon(i) for i in env.inbox.emails}
    elif suite == "banking":
        ba = env.bank_account
        e["iban"] = {canon(x) for t in ba.transactions + ba.scheduled_transactions for x in (t.sender, t.recipient)} | {canon(ba.iban)}
        e["id"] = {canon(t.id) for t in ba.scheduled_transactions}
    return e


KIND = {"hotel": "hotel", "restaurant": "restaurant", "company": "company", "event_id": "event_id",
        "recipients": "email", "cc": "email", "bcc": "email", "participants": "email", "email": "email",
        "user_email": "email", "user": "user", "channel": "channel", "url": "url", "file_id": "file_id",
        "email_id": "email_id"}


def kind_of(suite, arg):
    if suite == "banking":
        return {"recipient": "iban", "id": "id"}.get(arg)
    if suite == "slack" and arg == "recipient":
        return "user"
    return KIND.get(arg)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main():
    from agentdojo.task_suite.load_suites import get_suite
    d = json.load(gzip.open(os.path.join(HERE, "results", "residuals_routes_final2.json.gz")))
    rows = d["route2"]
    plan_has = {(s["task"], s["sink"]): s["plan_has_sink"] for s in d["route2_stats"] if "task" in s}
    ents = {s: entities(s, get_suite("v1", s).load_and_inject_default_environment({}))
            for s in ("banking", "slack", "travel", "workspace")}
    cfg = {s: yaml.safe_load(open(os.path.join(HERE, "config_m1_content", f"{s}.yaml"))) for s in ents}
    kept, dropped, magnitude = [], 0, []
    for r in rows:
        k = kind_of(r["suite"], r["arg"])
        v = r["call"][r["arg"]]
        vals = v if isinstance(v, list) else [v]
        if k is None:
            magnitude.append(r)  # an amount or another non-entity argument: any value executes
            continue
        if all(canon(x) in ents[r["suite"]][k] for x in vals):
            kept.append(r)
        else:
            dropped += 1
    out = {"candidates": len(rows), "not_entities": dropped, "entity_candidates": len(kept),
           "non_entity_args": collections.Counter(r["arg"] for r in magnitude)}
    for source in ("L1", "L2"):
        adm = [r for r in kept if r["res"]["b"][0] and r["res"]["b"][1] == source]
        pts = collections.defaultdict(set)
        for r in adm:
            pts[(r["suite"], r["task"], r["sink"], r["arg"])].add(json.dumps(r["call"][r["arg"]], default=str))
        ks = []
        for p, vs in pts.items():
            if source == "L2":
                o = (cfg[p[0]].get("operator_sets") or {}).get(p[2], {}).get(p[3])
                ks.append(len(o) if o else len(vs) + 1)
            else:
                ks.append(len(vs) + (1 if plan_has.get((p[1], p[2])) else 0))
        out[source] = {"admitted": len(adm), "decision_points": len(ks),
                       "k": ks and [statistics.median(ks), pct(ks, 0.9), max(ks)],
                       "share_k_gt_1": ks and round(sum(k > 1 for k in ks) / len(ks), 2),
                       "by_suite_arg": collections.Counter(f"{r['suite']}/{r['arg']}" for r in adm).most_common()}
    mag_adm = [r for r in magnitude if r["res"]["b"][0]]
    out["non_entity_admitted"] = {"admitted": len(mag_adm),
                                  "by_source": collections.Counter(r["res"]["b"][1] for r in mag_adm)}
    json.dump(out, open(os.path.join(HERE, "results", "route2_entities.json"), "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
