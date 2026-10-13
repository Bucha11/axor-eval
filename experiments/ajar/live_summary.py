"""Summarise the live o4-mini AgentDojo logs (run_agentdojo.py, one log per job).

    python live_summary.py /path/to/live/

Benign jobs log one line per task ("[GOVERNED ] user_task_3 (benign) utility=Y");
attack jobs log one line per pair ("... utility=Y  attack_succeeded=n"). Halves of a
suite are combined from raw counts.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict

BENIGN = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+)\s+\(benign\)\s+utility=([Yn])")
ATTACK = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+)\s+x\s+(\S+)\s+utility=([Yn])\s+attack_succeeded=([Yn])")
ERR = re.compile(r"\[(GOVERNED|UNDEFENDED) ?\]\s+(\S+).*ERROR")
DENIALS = re.compile(r"benign denials:\s+(\d+)")


def main(d: str) -> dict:
    benign = defaultdict(lambda: {"ok": 0, "n": 0, "errors": 0, "denials": 0})
    attack = defaultdict(lambda: {"utility": 0, "asr": 0, "n": 0, "errors": 0})
    for path in sorted(glob.glob(os.path.join(d, "*.log"))):
        name = os.path.basename(path)[:-4]
        text = open(path).read()
        suite = name.split("_")[1]
        if name.startswith("benign_"):
            cond = name.split("_")[2]
            b = benign[(suite, cond)]
            for m in BENIGN.finditer(text):
                b["n"] += 1
                b["ok"] += m.group(3) == "Y"
            b["errors"] += len(ERR.findall(text))
            dm = DENIALS.search(text)
            if dm:
                b["denials"] += int(dm.group(1))
        else:
            for m in ATTACK.finditer(text):
                a = attack[(suite, m.group(1).lower())]
                a["n"] += 1
                a["utility"] += m.group(4) == "Y"
                a["asr"] += m.group(5) == "Y"
            for m in ERR.finditer(text):
                attack[(suite, m.group(1).lower())]["errors"] += 1
    out = {"benign": {f"{s}/{c}": v for (s, c), v in sorted(benign.items())},
           "attack": {f"{s}/{c}": v for (s, c), v in sorted(attack.items())}}
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "—"  # noqa: E731
    print(f"{'suite':10s} {'undef CU':>14s} {'gov CU':>14s} {'cost':>8s}   denials  errors")
    tot = {"undefended": [0, 0], "governed": [0, 0]}
    for s in ("banking", "slack", "travel", "workspace"):
        u, g = benign[(s, "undefended")], benign[(s, "governed")]
        for c, v in (("undefended", u), ("governed", g)):
            tot[c][0] += v["ok"]
            tot[c][1] += v["n"]
        cost = (100 * g["ok"] / g["n"] - 100 * u["ok"] / u["n"]) if u["n"] and g["n"] else float("nan")
        print(f"{s:10s} {pct(u['ok'], u['n']):>8s} ({u['ok']}/{u['n']}) {pct(g['ok'], g['n']):>7s} ({g['ok']}/{g['n']}) "
              f"{cost:+7.1f}pp   {g['denials']:>4d}    {u['errors'] + g['errors']}")
    (uo, un), (go, gn) = tot["undefended"], tot["governed"]
    print(f"{'all':10s} {pct(uo, un):>8s} ({uo}/{un}) {pct(go, gn):>7s} ({go}/{gn}) "
          f"{(100 * go / gn - 100 * uo / un) if un and gn else float('nan'):+7.1f}pp")
    print("\nASR on the paper's curated slice")
    for s in ("banking", "slack", "travel", "workspace"):
        u, g = attack[(s, "undefended")], attack[(s, "governed")]
        print(f"{s:10s} undefended ASR {pct(u['asr'], u['n'])} ({u['asr']}/{u['n']})  "
              f"governed ASR {pct(g['asr'], g['n'])} ({g['asr']}/{g['n']})  "
              f"utility under attack {pct(u['utility'], u['n'])} -> {pct(g['utility'], g['n'])}")
    return out


if __name__ == "__main__":
    res = main(sys.argv[1])
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "live_o4mini.json")
    json.dump(res, open(out, "w"), indent=1)
