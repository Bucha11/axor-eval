"""Stage 0, all formats: utility; calls carrying a reference (whole or mangled) or a raw minted value;
mangled references (a minted code in an argument without its whole token, or a reference-shaped
token not in the session table); mangled calls that errored; raw minted values not in the request.

    python analyze_mangled.py -> analysis_mangled.json
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from refs import ANY_REF, DESCR  # noqa: E402


ID_ARGS = {"id", "id_", "file_id", "event_id", "email_id"}


def own_sets():
    import yaml
    return {su: {str(v).casefold() for v in (yaml.safe_load(open(os.path.join(HERE, "..", "config_m1_c814", f"{su}.yaml")))
                                             .get("audience") or ())} for su in ("banking", "slack", "travel", "workspace")}


def code(tok):
    if tok.isdigit():  # (0c) an integer handle is its own code
        return tok
    if tok.startswith("⟨"):
        return tok[1:-1].split(":", 1)[1].split("…")[0]
    return tok.rsplit("_", 1)[1]


def main():
    res = {}
    OWN = own_sets()
    for fmt in ("opaque", "hint", "descr", "descr_note", "descr_v2"):
        files = sorted(glob.glob(os.path.join(HERE, "runs", fmt, "*.json")))
        if not files:
            continue
        r = dict(episodes=0, utility=0, calls=0, target_calls=0, mangled_calls=0, mangled_with_error=0,
                 raw_calls=0, whole_ref_calls=0, episodes_with_mangled=0, failed=[])
        for p in files:
            d = json.load(open(p))
            r["episodes"] += 1
            r["utility"] += d["utility"]
            toks = set(d["refs"])
            codes = {code(t): t for t in toks}
            vals = {str(v) for _k, v in d["refs"].values()}
            ep_m = 0
            for c in d["calls"]:
                r["calls"] += 1
                mangled = whole = raw = False
                for _k, v in c["written"].items():
                    s = json.dumps(v, ensure_ascii=False)
                    has_whole = any(t in s for t in toks)
                    whole |= has_whole
                    for cd, t in codes.items():
                        if re.search(r"(?<![0-9a-f])" + cd + r"(?![0-9a-f])", s) and t not in s:
                            mangled = True
                    pat = DESCR if fmt.startswith("descr") else ANY_REF
                    if fmt == "descr_v2":
                        pass  # integer handles are checked below
                    if any(m.group(0) not in toks for m in pat.finditer(s)):
                        mangled = True
                    if any(x in s for x in vals if len(x) > 3 and x not in d["prompt"]):
                        raw = True
                    # (0c) an integer id argument that is neither a handle nor a value shown raw
                    if fmt == "descr_v2" and _k in ID_ARGS and isinstance(v, int) and not isinstance(v, bool) \
                            and str(v) not in toks and str(v).casefold() not in OWN[d["suite"]] \
                            and str(v) not in d["prompt"]:
                        mangled = True
                if mangled or whole or raw:
                    r["target_calls"] += 1
                r["whole_ref_calls"] += whole and not mangled
                r["mangled_calls"] += mangled
                r["mangled_with_error"] += bool(mangled and c["error"])
                r["raw_calls"] += raw
                ep_m += mangled
            r["episodes_with_mangled"] += bool(ep_m)
            if not d["utility"]:
                r["failed"].append(f"{d['suite']}/{d['user_task_id']}")
        r["mangled_share_target"] = round(r["mangled_calls"] / max(r["target_calls"], 1), 3)
        r["mangled_share_all"] = round(r["mangled_calls"] / max(r["calls"], 1), 3)
        res[fmt] = r
        print(fmt, {k: v for k, v in r.items() if k != "failed"})
        print("   failed:", r["failed"])
    json.dump(res, open(os.path.join(HERE, "analysis_mangled.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
