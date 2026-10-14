"""Revision 12: config_p12/ = config_p11/ with the O-derived enums moved from value_policies
into operator_sets (they declare O, they refuse nothing).

    python derive_p12.py
"""
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
for s in ("banking", "slack", "travel", "workspace"):
    c = yaml.safe_load(open(os.path.join(HERE, "config_p11", f"{s}.yaml")))
    sets, keep = {}, {}
    for tool, preds in (c.pop("value_policies", None) or {}).items():
        for p in preds:
            if p.get("kind") == "enum":
                sets.setdefault(tool, {})[p["arg"]] = list(p["allowed"])
            else:
                keep.setdefault(tool, []).append(p)
    if keep:
        c["value_policies"] = keep
    c["operator_sets"] = sets
    os.makedirs(os.path.join(HERE, "config_p12"), exist_ok=True)
    with open(os.path.join(HERE, "config_p12", f"{s}.yaml"), "w") as fh:
        fh.write(f"# config_p11/{s}.yaml with O as operator_sets (residuals_rules.md revision 12;\n"
                 "# derive_p12.py). Do not edit by hand.\n")
        yaml.safe_dump(c, fh, sort_keys=False)
    print(s, {t: {a: len(v) for a, v in x.items()} for t, x in sets.items()}, "| refusing value_policies left:", keep or None)
