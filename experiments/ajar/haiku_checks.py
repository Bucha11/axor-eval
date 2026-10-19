"""Pre-publication checks on the completed Haiku run (read-only, no API):
1. Cost ± population SD by suite and all (same formula as cost_table_origin_c9v5.py), full Table-4.
2. Confirmations per EPISODE (conf/(tasks*passes)) by suite+all; approved/asked; cap-5 exhaustion;
   any approved addressee NOT in the request.
3. slack/4 KeyError handling: final-data flags; o4-mini path noted in the report.
Plus: slack 7 & 12 admitted-call grant_source/description (designation by channel name?)."""
import json, glob, os, statistics
from collections import defaultdict
H = "results/haiku_full"
SUITES = ("banking", "slack", "travel", "workspace")
NTASK = {"banking": 16, "slack": 20, "travel": 20, "workspace": 40}  # after slack/4 exclusion
EXCL = {("slack", "user_task_4")}


def load(cond):
    """(suite,tid) -> [p1,p2,p3] utility; excludes slack/4."""
    out = {}
    for pi, p in enumerate(("pass1", "pass2", "pass3")):
        for s in SUITES:
            for f in glob.glob(os.path.join(H, cond, p, s, "user_task_*.json")):
                tid = os.path.splitext(os.path.basename(f))[0].replace("_undefended", "")
                if (s, tid) in EXCL:
                    continue
                out.setdefault((s, tid), [None, None, None])[pi] = bool(json.load(open(f)).get("utility"))
    return {k: v for k, v in out.items() if all(x is not None for x in v)}


U = load("undefended"); O = load("origin"); G = load("grants"); G4 = load("grants_l4")


def pct(pt, s, pi):
    ks = [k for k in pt if k[0] == s] if s else list(pt)
    return 100.0 * sum(pt[k][pi] for k in ks) / len(ks)


def util_all(pt, s=None):
    ks = [k for k in pt if k[0] == s] if s else list(pt)
    su = sum(sum(pt[k]) for k in ks); de = sum(len(pt[k]) for k in ks)
    return 100.0 * su / de


def cost(pt, s):
    d = [pct(pt, s, i) - pct(U, s, i) for i in range(3)]
    return statistics.mean(d), statistics.pstdev(d), d


print("===== CHECK 1: Table 4 (Haiku, excl slack/4) — util% and Cost(pp)=defended-undef, mean±popSD over 3 passes =====")
hdr = f"{'suite':<12}{'Undef':>7}{'origin util/cost':>22}{'grants util/cost':>22}{'grants+L4 util/cost':>24}"
print(hdr)
for s in list(SUITES) + [None]:
    name = f"{s} ({NTASK[s]})" if s else "all (96)"
    uu = util_all(U, s)
    om, osd, od = cost(O, s); gm, gsd, gd = cost(G, s); lm, lsd, ld = cost(G4, s)
    print(f"{name:<12}{uu:>6.1f}%  {util_all(O,s):>5.1f}% {om:>+5.1f}±{osd:<4.1f} {util_all(G,s):>5.1f}% {gm:>+5.1f}±{gsd:<4.1f}  {util_all(G4,s):>5.1f}% {lm:>+5.1f}±{lsd:<4.1f}")
    if s is None:
        print(f"    per-pass diffs  origin={['%+.1f'%x for x in od]}  grants={['%+.1f'%x for x in gd]}  grants+L4={['%+.1f'%x for x in ld]}")

print("\n===== CHECK 2: L4 confirmations (grants_l4) =====")
conf_asked = defaultdict(int); conf_appr = defaultdict(int); over_budget = []
nonreq_approved = []
for p in ("pass1", "pass2", "pass3"):
    for s in SUITES:
        for f in glob.glob(os.path.join(H, "grants_l4", p, s, "user_task_*.json")):
            tid = os.path.splitext(os.path.basename(f))[0]
            d = json.load(open(f))
            st = d.get("l4") or {}
            conf_asked[s] += st.get("asked", 0); conf_appr[s] += st.get("approved", 0)
            if st.get("over_budget") or st.get("terminated"):
                over_budget.append((s, tid, p, st))
            prompt = ""
            for m in (d.get("messages") or []):
                if m.get("role") == "user":
                    c = m.get("content")
                    prompt += " ".join(b.get("content", "") for b in c) if isinstance(c, list) else str(c)
            pl = prompt.casefold()
            for dec in (d.get("l4_decisions") or []):
                if dec.get("approved"):
                    args = (dec.get("call") or [None, {}])[1] or {}
                    for a, v in args.items():
                        for one in (v if isinstance(v, list) else [v]):
                            sv = str(one).strip().casefold()
                            if len(sv) > 2 and sv not in pl and a in ("recipient", "user", "user_email", "channel", "email", "to", "address"):
                                nonreq_approved.append((s, tid, p, a, str(one)))
tot_ep = {s: NTASK[s] * 3 for s in SUITES}
A = sum(conf_asked.values()); AP = sum(conf_appr.values()); EP = sum(tot_ep.values())
print(f"{'suite':<10}{'asked':>7}{'approved':>10}{'episodes':>10}{'conf/episode':>14}")
for s in SUITES:
    print(f"{s:<10}{conf_asked[s]:>7}{conf_appr[s]:>10}{tot_ep[s]:>10}{conf_asked[s]/tot_ep[s]:>14.3f}")
print(f"{'ALL':<10}{A:>7}{AP:>10}{EP:>10}{A/EP:>14.3f}   (o4-mini: 60/288=0.208)")
print(f"approved/asked = {AP}/{A}")
print(f"cap-5 exhausted/terminated episodes: {len(over_budget)}  {over_budget[:5]}")
print(f"approved addressees NOT in request: {len(nonreq_approved)}  {nonreq_approved[:10]}")

print("\n===== CHECK 3: slack/4 (KeyError task) in final data =====")
for p in ("pass1", "pass2", "pass3"):
    for cond in ("undefended", "origin", "grants", "grants_l4"):
        fs = glob.glob(os.path.join(H, cond, p, "slack", "user_task_4*.json"))
        for f in fs:
            d = json.load(open(f))
            print(f"  {cond:<11} {p}: utility={d.get('utility')} utility_error={d.get('utility_error')} api_error={d.get('api_error')} ncalls={len(d.get('calls') or [])}")

print("\n===== slack 7 & 12: admitted-call grant_source/description (designation?) =====")
for tid in ("user_task_7", "user_task_12"):
    print(f"-- slack/{tid}")
    for cond in ("grants", "grants_l4"):
        for p in ("pass1", "pass2", "pass3"):
            fs = glob.glob(os.path.join(H, cond, p, "slack", f"{tid}.json"))
            for f in fs:
                d = json.load(open(f))
                for c in (d.get("calls") or []):
                    if c.get("allowed"):
                        gs = c.get("grant_source"); ds = c.get("description")
                        if gs or ds:
                            print(f"   {cond} {p} {c.get('tool')} allowed via grant_source={gs} desc={str(ds)[:60]}")
                break
