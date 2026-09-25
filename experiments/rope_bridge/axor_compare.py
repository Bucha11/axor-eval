"""Unified corrected aggregator: axor origin vs undefended vs ROPE, per suite.
Applies ROPE's effect-based corrections (slack IT5 etc.) uniformly to every arm.
Run from the ROPE repo root with PYTHONPATH including runs/ and autodojo/src, src/.
"""
import glob, json, re, sys
from collections import defaultdict
sys.path.insert(0, "runs")
import corrections

TAG = "gpt-4o-mini-2024-07-18-openrouter"
AXR = "runs_axor"
ROPE = "src/rope/runs"

def _origin_dir(suite):
    # banking dir has no suite segment in the name; slack/travel do
    for cand in (f"{AXR}/{TAG}-axor-{suite}-governed-origin/{suite}",
                 f"{AXR}/{TAG}-axor-governed-origin/{suite}"):
        if glob.glob(cand + "/user_task_*"):
            return cand
    return None

def _undef_dir(suite):
    for cand in (f"{AXR}/{TAG}-axor-{suite}-undefended/{suite}",
                 f"{AXR}/{TAG}-axor-undefended/{suite}"):
        if glob.glob(cand + "/user_task_*"):
            return cand
    return None

def _rope_dir(suite):
    return f"{ROPE}/{TAG}-rope-opus/{suite}"

def agg(root, suite):
    if not root:
        return None
    clean = glob.glob(root + "/user_task_*/none/none.json")
    atk = glob.glob(root + "/user_task_*/important_instructions/injection_task_*.json")
    cu = [bool(json.load(open(f)).get("utility")) for f in clean]
    ua, asr = [], []
    byit = defaultdict(lambda: [0, 0])
    for f in atk:
        d = json.load(open(f)); it = int(re.search(r"injection_task_(\d+)", f).group(1))
        ua.append(bool(d.get("utility")))
        s = corrections.corrected_security(d, suite, it)
        asr.append(s); byit[it][0] += s; byit[it][1] += 1
    pct = lambda xs: (100 * sum(xs) / len(xs)) if xs else float("nan")
    return dict(CU=pct(cu), UA=pct(ua), ASR=pct(asr), n_clean=len(cu), n_atk=len(asr),
                byit={k: tuple(v) for k, v in sorted(byit.items())})

for suite in ("banking", "slack", "travel"):
    print(f"\n==== {suite} (corrected ASR) ====")
    for label, root in (("axor origin", _origin_dir(suite)),
                        ("undefended", _undef_dir(suite)),
                        ("ROPE opus", _rope_dir(suite))):
        r = agg(root, suite)
        if r is None:
            print(f"  {label:12} (no logs)"); continue
        print(f"  {label:12} CU={r['CU']:5.1f}  UA={r['UA']:5.1f}  ASR={r['ASR']:5.1f}  "
              f"(n_clean={r['n_clean']} n_atk={r['n_atk']})")
        if label == "axor origin":
            print(f"               per-IT successes: {r['byit']}")
