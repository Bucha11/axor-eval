"""CU / UA / corrected ASR for the re-measured axor rows next to the old table.

    cd $ROPE && PYTHONPATH=autodojo/src:src:runs python .../aggregate.py runs_axor_rule

Undefended, ROPE and the old axor-origin rows are copied from
experiments/rope_bridge/README.md (branch claude/rope-axor-analysis-syszaz),
not re-run. ASR uses ROPE's corrections.corrected_security, as before.
"""
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

import corrections

TAG = "gpt-4o-mini-2024-07-18-openrouter"
OLD = {  # suite: {row: (CU, UA, ASR)}
    "banking": {"undefended": (56.2, 43.1, 54.2), "ROPE": (50.0, None, 0.0), "axor origin (old)": (43.8, 40.3, 0.0)},
    "slack": {"undefended": (71.4, 51.4, 66.7), "ROPE": (71.4, 53.3, 4.8), "axor origin (old)": (52.4, 36.2, 1.9)},
    "travel": {"undefended": (55.0, 37.1, 30.0), "ROPE": (50.0, 48.6, 7.1), "axor origin (old)": (55.0, 45.7, 12.9)},
}


def agg(root):
    clean = glob.glob(f"{root}/user_task_*/none/none.json")
    atk = glob.glob(f"{root}/user_task_*/important_instructions/injection_task_*.json")
    suite = Path(root).name
    cu = [bool(json.load(open(f)).get("utility")) for f in clean]
    ua, asr, raw, landed = [], [], [], []
    for f in atk:
        d = json.load(open(f))
        it = int(re.search(r"injection_task_(\d+)", f).group(1))
        ua.append(bool(d.get("utility")))
        s = bool(corrections.corrected_security(d, suite, it))
        asr.append(s)
        raw.append(bool(d.get("security")))
        if s:
            landed.append(f"{Path(f).parents[1].name}/it{it}")
    pct = lambda xs: 100 * sum(xs) / len(xs) if xs else float("nan")
    return dict(CU=pct(cu), UA=pct(ua), ASR=pct(asr), raw_ASR=pct(raw),
                n_clean=len(cu), n_atk=len(asr), landed=landed)


def main(base):
    out = {}
    for suite in ("banking", "slack", "travel"):
        print(f"\n{suite}")
        print(f"  {'row':26s} {'CU':>6s} {'UA':>6s} {'ASR':>6s}")
        for row, v in OLD[suite].items():
            f = lambda x: f"{x:6.1f}" if x is not None else "     —"
            print(f"  {row:26s} {f(v[0])} {f(v[1])} {f(v[2])}")
        out[suite] = {}
        for arm in ("rule", "rule-grants"):
            r = agg(f"{base}/{TAG}-axor-{suite}-{arm}/{suite}")
            out[suite][arm] = r
            print(f"  {'axor ' + arm:26s} {r['CU']:6.1f} {r['UA']:6.1f} {r['ASR']:6.1f}"
                  f"   (n={r['n_clean']}/{r['n_atk']}, raw ASR {r['raw_ASR']:.1f}, landed {r['landed']})")
    out["old"] = OLD
    json.dump(out, open(Path(__file__).parent / "results.json", "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs_axor_rule")
