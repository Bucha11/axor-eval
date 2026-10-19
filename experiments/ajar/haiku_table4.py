"""Haiku Table-4 analysis — SAME methods as the o4-mini table (cost_table_origin_c9v5.py):
utility% = successes/episodes; Cost(pp) = pass-i governed − pass-i undefended, mean ± population SD
over 3 passes; paired diff = task bootstrap n=2000 seed=0, 95% percentile CI. slack user_task_4
excluded (as o4-mini); §7.3 variant also excludes slack user_task_7 and user_task_12. NO API calls."""
import json, glob, os, statistics, random
R = "/home/user/ajar-wt/experiments/ajar/results"
H = os.path.join(R, "haiku_full")
SUITES = ("banking", "slack", "travel", "travel") if False else ("banking", "slack", "travel", "workspace")
NICE = {"banking": "banking (16)", "slack": "slack (20)", "travel": "travel (20)", "workspace": "workspace (40)"}
CONDS = {"undefended": "undefended", "origin": "origin", "grants": "grants", "grants_l4": "grants_l4"}


def per_task_pass(cond, exclude):
    out = {}
    for pi, p in enumerate(("pass1", "pass2", "pass3")):
        for s in SUITES:
            for f in glob.glob(os.path.join(H, cond, p, s, "user_task_*.json")):
                tid = os.path.splitext(os.path.basename(f))[0].replace("_undefended", "")
                if (s, tid) in exclude:
                    continue
                out.setdefault((s, tid), [None, None, None])[pi] = bool(json.load(open(f)).get("utility"))
    return {k: v for k, v in out.items() if all(x is not None for x in v)}


def suite_keys(pt, s):
    return [k for k in pt if k[0] == s]


def util_pct(pt, s=None):
    ks = suite_keys(pt, s) if s else list(pt)
    succ = sum(sum(pt[k]) for k in ks); den = sum(len(pt[k]) for k in ks)
    return (100.0 * succ / den if den else float("nan")), succ, den


def pct_pass_suite(pt, s, pi):
    ks = suite_keys(pt, s)
    return 100.0 * sum(pt[k][pi] for k in ks) / len(ks) if ks else float("nan")


def pct_pass_all(pt, pi):
    return 100.0 * sum(v[pi] for v in pt.values()) / len(pt)


def cost_pp(gov_passes, und_passes):
    d = [o - u for o, u in zip(gov_passes, und_passes)]
    return statistics.mean(d), statistics.pstdev(d)


def paired_bootstrap(X, Y, keys, n=2000, seed=0):
    keys = [k for k in keys if k in X and k in Y]
    xt = {k: (sum(X[k]), len(X[k])) for k in keys}
    yt = {k: (sum(Y[k]), len(Y[k])) for k in keys}
    point = 100.0 * (sum(yt[k][0] for k in keys) / sum(yt[k][1] for k in keys)
                     - sum(xt[k][0] for k in keys) / sum(xt[k][1] for k in keys))
    rng = random.Random(seed); k = len(keys); diffs = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        xn = sum(xt[keys[i]][0] for i in idx); xd = sum(xt[keys[i]][1] for i in idx)
        yn = sum(yt[keys[i]][0] for i in idx); yd = sum(yt[keys[i]][1] for i in idx)
        diffs.append(100.0 * (yn / yd - xn / xd))
    diffs.sort(); lo, hi = int(0.025 * n), int(0.975 * n) - 1
    return point, diffs[lo], diffs[hi]


def l4_stats(cond):
    asked = approved = 0; per_task = {}
    for p in ("pass1", "pass2", "pass3"):
        for s in SUITES:
            for f in glob.glob(os.path.join(H, cond, p, s, "user_task_*.json")):
                if (s, "user_task_4") == (s, os.path.splitext(os.path.basename(f))[0]):
                    pass
                d = json.load(open(f))
                st = d.get("l4") or {}
                asked += st.get("asked", 0); approved += st.get("approved", 0)
                c = (d.get("confirmations") or 0)
                per_task.setdefault((s, d.get("user_task_id")), []).append(c if isinstance(c, int) else 0)
    return asked, approved, per_task


def analyze(exclude, label):
    U = per_task_pass("undefended", exclude)
    O = per_task_pass("origin", exclude)
    G = per_task_pass("grants", exclude)
    G4 = per_task_pass("grants_l4", exclude)
    res = {"label": label, "n_tasks": len(U), "conditions": {}}
    for name, pt in [("undefended", U), ("origin", O), ("grants", G), ("grants_l4", G4)]:
        row = {"all": util_pct(pt)[0], "by_suite": {s: util_pct(pt, s)[0] for s in SUITES},
               "per_pass_all": [pct_pass_all(pt, i) for i in range(3)]}
        if name != "undefended":
            up = [pct_pass_all(U, i) for i in range(3)]; gp = [pct_pass_all(pt, i) for i in range(3)]
            m, sd = cost_pp(gp, up)
            row["cost_pp_vs_undef_all"] = {"mean": round(m, 1), "sd": round(sd, 1)}
            row["cost_pp_by_suite"] = {}
            for s in SUITES:
                ups = [pct_pass_suite(U, s, i) for i in range(3)]; gps = [pct_pass_suite(pt, s, i) for i in range(3)]
                mm, ss = cost_pp(gps, ups)
                row["cost_pp_by_suite"][s] = {"mean": round(mm, 1), "sd": round(ss, 1)}
        res["conditions"][name] = row
    # paired grants - origin
    allk = sorted(set(G) & set(O))
    pb = {"all": paired_bootstrap(O, G, allk)}
    for s in SUITES:
        pb[s] = paired_bootstrap(O, G, [k for k in allk if k[0] == s])
    res["paired_grants_minus_origin"] = {k: {"mean": round(v[0], 1), "ci": [round(v[1], 1), round(v[2], 1)]}
                                         for k, v in pb.items()}
    # L4 confirmations
    asked, approved, per_task = l4_stats("grants_l4")
    ntasks = len(per_task) or 1
    res["l4"] = {"asked": asked, "approved": approved,
                 "confirmations_per_task": round(sum(sum(v) for v in per_task.values()) / ntasks, 3)}
    return res


EXCL_BASE = {("slack", "user_task_4")}
EXCL_73 = EXCL_BASE | {("slack", "user_task_7"), ("slack", "user_task_12")}
out = {"model": "anthropic/claude-haiku-5.5", "kernel": "f227951", "reasoning": "{max_tokens:1024}",
       "backend": "openrouter (provider pinned Anthropic)",
       "main": analyze(EXCL_BASE, "exclude slack/4 (as o4-mini)"),
       "excl_slack_7_12": analyze(EXCL_73, "exclude slack/4 + slack/7 + slack/12 (§7.3)")}
# slack user_task_4 standalone
s4 = []
for p in ("pass1", "pass2", "pass3"):
    for cond in CONDS:
        f = glob.glob(os.path.join(H, cond, p, "slack", "user_task_4*.json"))
        if f:
            s4.append({"cond": cond, "pass": p, "utility": bool(json.load(open(f[0])).get("utility"))})
out["slack_user_task_4"] = s4
json.dump(out, open(os.path.join(R, "haiku_table4.json"), "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
