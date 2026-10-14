"""Stage 0 analysis (STAGE0.md): utility vs undefended pass 1; per call, distorted/invented
references and raw values in place of references; reference-caused tool errors.

    python analyze.py -> analysis.json (+ printed table)
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from refs import ANY_REF, EMAIL, IBAN, URL  # noqa: E402

ID_ARGS = {"id", "id_", "file_id", "event_id", "email_id"}


def leaves(x, key=None):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, k)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from leaves(v, key)
    else:
        yield key, x


def analyze(path):
    d = json.load(open(path))
    table = d["refs"]
    minted = {}  # value(str) -> kind
    for tok, (kind, v) in table.items():
        minted[str(v)] = kind
    prompt = d["prompt"]
    rows = []
    for c in d["calls"]:
        bad, raw, refs_used = [], [], []
        for key, v in leaves(c["written"]):
            if not isinstance(v, (str, int)):
                continue
            s = str(v)
            for m in ANY_REF.finditer(s):
                (refs_used if m.group(0) in table else bad).append(m.group(0))
            cands = [s] if key in ID_ARGS else []
            cands += EMAIL.findall(s) + IBAN.findall(s) + [u.rstrip(".;:!?") for u in URL.findall(s)]
            for x in cands:
                if x in minted and x not in prompt and (key in ID_ARGS or minted[x] != "id"):
                    raw.append(x)
        rows.append({"tool": c["tool"], "refs": refs_used, "bad": bad, "raw": raw,
                     "target": bool(refs_used or bad or raw), "error": c["error"],
                     "ref_error": bool(c["error"] and (bad or "⟨" in json.dumps(c["resolved"], ensure_ascii=False)))})
    return d, rows


def main():
    out = {}
    for fmt in ("opaque", "hint"):
        eps = []
        for p in sorted(glob.glob(os.path.join(HERE, "runs", fmt, "*.json"))):
            d, rows = analyze(p)
            eps.append({"suite": d["suite"], "task": d["user_task_id"], "utility": d["utility"], "error": d["error"],
                        "calls": len(rows), "target_calls": sum(r["target"] for r in rows),
                        "ref_calls": sum(bool(r["refs"]) for r in rows),
                        "bad_calls": sum(bool(r["bad"]) for r in rows), "raw_calls": sum(bool(r["raw"]) for r in rows),
                        "ref_errors": sum(r["ref_error"] for r in rows),
                        "bad": [x for r in rows for x in r["bad"]], "raw": [x for r in rows for x in r["raw"]]})
        n = sum(e["calls"] for e in eps)
        t = sum(e["target_calls"] for e in eps)
        tot = {"episodes": len(eps), "utility": sum(e["utility"] for e in eps), "calls": n, "target_calls": t,
               "ref_calls": sum(e["ref_calls"] for e in eps), "bad_calls": sum(e["bad_calls"] for e in eps),
               "raw_calls": sum(e["raw_calls"] for e in eps), "ref_errors": sum(e["ref_errors"] for e in eps)}
        tot["bad_share_all"] = round(tot["bad_calls"] / max(n, 1), 4)
        tot["bad_share_target"] = round(tot["bad_calls"] / max(t, 1), 4)
        tot["raw_share_target"] = round(tot["raw_calls"] / max(t, 1), 4)
        out[fmt] = {"total": tot, "episodes": eps}
        print(fmt, json.dumps(tot))
        for e in eps:
            if not e["utility"] or e["bad"] or e["raw"] or e["ref_errors"] or e["error"]:
                print("   ", e["suite"], e["task"], "util", e["utility"], "bad", e["bad"], "raw", e["raw"],
                      "ref_err", e["ref_errors"], e["error"] or "")
    json.dump(out, open(os.path.join(HERE, "analysis.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
