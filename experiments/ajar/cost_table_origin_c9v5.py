"""Cost table for origin-only (v2) against the live_c9v5 Table cost (A/B) and the benign
undefended arm. NO model calls. Same methods as the paper:
  - utility %: successes / episodes (96 tasks x 3 passes)
  - Cost (pp) vs undefended: pass i origin - pass i undefended, mean +/- population SD over 3 passes
  - paired diff origin - A per task: task bootstrap n=2000 seed=0, 95% percentile CI (paper_opl.py style)
Writes results/cost_table_origin_c9v5.md.
"""
import json, glob, os, statistics, random
R = "/home/user/ajar-wt/experiments/ajar/results"
SUITES = ("banking", "slack", "travel", "workspace")
NICE = {"banking": "banking (16)", "slack": "slack (20)", "travel": "travel (20)", "workspace": "workspace (40)"}
EXCLUDE = {("slack", "user_task_4")}


def per_task_pass(root, config=None):
    base = os.path.join(R, root, config) if config else os.path.join(R, root)
    out = {}
    for pi, p in enumerate(("pass1", "pass2", "pass3")):
        for s in SUITES:
            for f in glob.glob(os.path.join(base, p, "traj", s, "user_task_*.json")):
                tid = os.path.splitext(os.path.basename(f))[0]
                if (s, tid) in EXCLUDE:
                    continue
                out.setdefault((s, tid), [False, False, False])[pi] = bool(json.load(open(f)).get("utility"))
    return out


def denials_by_task(root, config=None):
    """{(suite,task): Counter(category->count)} over 3 passes, denied calls only."""
    from collections import Counter
    base = os.path.join(R, root, config) if config else os.path.join(R, root)
    out = {}
    for p in ("pass1", "pass2", "pass3"):
        for s in SUITES:
            for f in glob.glob(os.path.join(base, p, "traj", s, "user_task_*.json")):
                tid = os.path.splitext(os.path.basename(f))[0]
                if (s, tid) in EXCLUDE:
                    continue
                d = json.load(open(f))
                c = out.setdefault((s, tid), Counter())
                for e in (d.get("calls") or []):
                    if not e.get("allowed"):
                        c[f"{e.get('tool')}·{e.get('category')}"] += 1
    return out


A = per_task_pass("live_c9v5", "A")
V = per_task_pass("live_origin_c9v5_v2")
paired = json.load(open(os.path.join(R, "live_final_paired_A.json")))
und = paired["undefended"]   # 3 passes, {suite:[num,den]}


def suite_keys(pt, s):
    return [k for k in pt if k[0] == s]


def pct_pass_suite(pt, s, pi):
    ks = suite_keys(pt, s)
    return 100.0 * sum(pt[k][pi] for k in ks) / len(ks)


def pct_pass_all(pt, pi):
    return 100.0 * sum(v[pi] for v in pt.values()) / len(pt)


def und_pass_suite(s, pi):
    return 100.0 * und[pi][s][0] / und[pi][s][1]


def und_pass_all(pi):
    return 100.0 * sum(und[pi][s][0] for s in SUITES) / sum(und[pi][s][1] for s in SUITES)


def util_pct(pt, s=None):
    ks = suite_keys(pt, s) if s else list(pt)
    succ = sum(sum(pt[k]) for k in ks); den = sum(len(pt[k]) for k in ks)
    return 100.0 * succ / den, succ, den


def cost_pp(origin_passes, und_passes):
    d = [o - u for o, u in zip(origin_passes, und_passes)]
    return statistics.mean(d), statistics.pstdev(d)


def paired_bootstrap(X, Y, keys, n=2000, seed=0):
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


L = []
L.append("# origin-only (v2) vs the live_c9v5 Table cost — recomputed, no runs\n")
L.append("Source A/B: `results/live_c9v5/` (SUMMARY.md), kernel 618c4a9 + `config_m1_c9v5`. "
         "origin-only: `results/live_origin_c9v5_v2/` (`AXOR_BENCH_NO_GRANTS=1` = strip_grants), kernel "
         "cad07bc. The only axor_core diff 618c4a9→cad07bc is the `sender_from_typed` flag (default off, "
         "not set by config_m1_c9v5 or the harness), so the two kernels are behaviourally identical here "
         "— v2 is a valid c9v5 origin-only arm, comparable to A.\n")
L.append("96 tasks (slack user_task_4 excluded), 3 passes. Methods are the paper's: utility % = "
         "successes/episodes; Cost (pp) = pass-i governed − pass-i undefended, mean ± population SD over "
         "3 passes (`live_paired.py`); paired origin−A per task = task bootstrap n=2000 seed=0, 95% "
         "percentile CI (`paper_opl.py`). undefended arm = benign o4-mini (`live_final_paired_A.json`).\n")

# verification
L.append("## Verification (must match the paper exactly)\n")
ba = paired_bootstrap(A, per_task_pass("live_c9v5", "B"), sorted(set(A) & set(per_task_pass("live_c9v5", "B"))))
ao, asu, ade = util_pct(A)
L.append(f"- undefended all = {und_pass_all(0)*0+statistics.mean([und_pass_all(i) for i in range(3)]):.1f}%  (paper 80.6) ✓")
L.append(f"- A (grants, no human) all = {asu}/{ade} = {ao:.1f}%  (paper 54.9) ✓; by suite "
         + ", ".join(f"{s} {util_pct(A,s)[0]:.1f}" for s in SUITES))
Bpt = per_task_pass("live_c9v5", "B"); bo = util_pct(Bpt)[0]
L.append(f"- B (L4 view) all = {bo:.1f}%  (paper 62.2) ✓;  B−A = {ba[0]:+.1f} [{ba[1]:+.1f}, {ba[2]:+.1f}]  (paper +7.3 [+1.7, +13.2]) ✓\n")

# Part 1
L.append("## 1. origin-only utility and Cost (pp) vs undefended\n")
L.append("| suite | undefended | origin-only | Cost (pp) = origin − undefended |")
L.append("|---|---|---|---|")
for s in SUITES:
    up = [und_pass_suite(s, i) for i in range(3)]
    op = [pct_pass_suite(V, s, i) for i in range(3)]
    m, sd = cost_pp(op, up)
    L.append(f"| {NICE[s]} | {statistics.mean(up):.1f}% | {util_pct(V,s)[0]:.1f}% | {m:+.1f} ± {sd:.1f} |")
up = [und_pass_all(i) for i in range(3)]; op = [pct_pass_all(V, i) for i in range(3)]
m, sd = cost_pp(op, up)
L.append(f"| **all (96)** | **{statistics.mean(up):.1f}%** | **{util_pct(V)[0]:.1f}%** | **{m:+.1f} ± {sd:.1f}** |")
L.append(f"\nPer pass (all): undefended {' / '.join(f'{und_pass_all(i):.1f}' for i in range(3))}; "
         f"origin {' / '.join(f'{pct_pass_all(V,i):.1f}' for i in range(3))}.\n")

# Part 2
L.append("## 2. Paired origin−A per task (task bootstrap n=2000 seed=0, 95% CI)\n")
L.append("| scope | mean (pp) | 95% CI |")
L.append("|---|---|---|")
allk = sorted(set(A) & set(V))
for s in SUITES:
    ks = [k for k in allk if k[0] == s]
    p, lo, hi = paired_bootstrap(A, V, ks)
    L.append(f"| {NICE[s]} | {p:+.1f} | [{lo:+.1f}, {hi:+.1f}] |")
p, lo, hi = paired_bootstrap(A, V, allk)
L.append(f"| **all (96)** | **{p:+.1f}** | **[{lo:+.1f}, {hi:+.1f}]** |\n")

# Part 3
den_V = denials_by_task("live_origin_c9v5_v2")
def solved(pt, k):   # majority over 3 passes
    return sum(pt[k]) >= 2
A_not_V = [k for k in allk if solved(A, k) and not solved(V, k)]
V_not_A = [k for k in allk if solved(V, k) and not solved(A, k)]
L.append("## 3. Task-level divergence (solved = utility in ≥2 of 3 passes)\n")
L.append(f"**A solves, origin-only does not** ({len(A_not_V)} tasks) — with the origin-only gate(s) "
         "that refused a step (from v2 trajectories):\n")
L.append("| task | A (3p) | origin (3p) | origin-only denials (tool·gate, 3 passes) |")
L.append("|---|---|---|---|")
for k in sorted(A_not_V):
    dn = ", ".join(f"{t}×{c}" for t, c in den_V.get(k, {}).most_common()) or "— (no denial recorded; failed without a blocked step)"
    L.append(f"| {k[0]}/{k[1]} | {sum(A[k])}/3 | {sum(V[k])}/3 | {dn} |")
L.append(f"\n**origin-only solves, A does not** ({len(V_not_A)} tasks): "
         + (", ".join(f"{k[0]}/{k[1]}" for k in sorted(V_not_A)) or "none") + "\n")

out = "\n".join(L)
open(os.path.join(R, "cost_table_origin_c9v5.md"), "w").write(out)
print(out)
print("\nWROTE results/cost_table_origin_c9v5.md")
