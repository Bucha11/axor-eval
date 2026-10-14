"""Revision 11: config_p11/ = config_p10/ + secrets (revision 10 item 2, as in config_p10s/)
+ the addressed floor (audience = O ∪ the user's identifiers; destination args by name;
shared stores as revision 2).

    python derive_p11.py   (Ajar venv: imports residuals for SHARED)
"""
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SUITES = ("banking", "slack", "travel", "workspace")
DEST = {"recipient", "recipients", "cc", "bcc", "participants", "email", "user_email", "user",
        "channel", "url", "hotel", "restaurant", "company"}
USER_IDS = {"banking": ["DE89370400440532013000"], "slack": [],
            "travel": ["emma.johnson@bluesparrowtech.com"], "workspace": ["emma.johnson@bluesparrowtech.com"]}


def main():
    from agentdojo.task_suite.load_suites import get_suite
    from residuals import SHARED
    o = json.load(open(os.path.join(HERE, "results", "operator_o.json")))
    os.makedirs(os.path.join(HERE, "config_p11"), exist_ok=True)
    for s in SUITES:
        c = yaml.safe_load(open(os.path.join(HERE, "config_p10", f"{s}.yaml")))
        sec = yaml.safe_load(open(os.path.join(HERE, "config_p10s", f"{s}.yaml")))["sensitive_sources"]
        tools = {f.name: f for f in get_suite("v1", s).tools}
        dest = {}
        for t in c.get("egress_sinks") or []:
            props = tools[t].parameters.model_json_schema().get("properties", {})
            d = sorted(a for a in props if a in DEST)
            if d:
                dest[t] = d
        aud = sorted({v for vs in o[s]["O"].values() for v in vs} | set(USER_IDS[s]))
        c["sensitive_sources"] = sec
        c["floor_mode"] = "audience"
        c["audience"] = aud
        c["destination_args"] = dest
        c["shared_stores"] = SHARED[s]
        with open(os.path.join(HERE, "config_p11", f"{s}.yaml"), "w") as fh:
            fh.write(f"# config_p10/{s}.yaml + secrets + addressed floor (residuals_rules.md revision 11;\n"
                     "# derive_p11.py). Do not edit by hand.\n")
            yaml.safe_dump(c, fh, sort_keys=False)
        print(f"== {s}: |audience|={len(aud)}  secrets={sec}\n   destination args={dest}\n   shared={SHARED[s]}")


if __name__ == "__main__":
    main()
