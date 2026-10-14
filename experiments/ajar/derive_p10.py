"""Revision 10 (proven polarity): config_p10/ and config_p10s/ from config_rule_l2o/,
the tool schemas and config_o4p/SINKS.md (class by type of effect). No task, no ground truth.

    python derive_p10.py
"""
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from derive_grants import is_rich  # noqa: E402

SUITES = ("banking", "slack", "travel", "workspace")
# SINKS.md "why" -> kernel class (residuals_rules.md revision 10, item 1)
WHY = {
    "moves money": "consequential", "sends outside the workspace": "consequential",
    "shares outward": "consequential", "network read, no user data": "consequential",  # a web fetch
    "deletes": "catastrophic", "changes credentials": "catastrophic",
    "changes state inside the workspace": "reversible",
}
# item 2: public reads (third-party published content or workspace structure)
PUBLIC = re.compile(r"hotel|restaurant|car_|car$|flight|webpage|get_channels|users_in_channel|current_day")


def sinks_md():
    out = {}
    for line in open(os.path.join(HERE, "config_o4p", "SINKS.md")):
        m = re.match(r"\| (\w+) \| `(\w+)` \| \*\*\w+\*\* \| ([^|]+) \|", line)
        if m:
            out[(m.group(1), m.group(2))] = WHY[m.group(3).strip()]
    return out


def main():
    from agentdojo.task_suite.load_suites import get_suite
    why = sinks_md()
    for suite_name in SUITES:
        base = yaml.safe_load(open(os.path.join(HERE, "config_rule_l2o", f"{suite_name}.yaml")))
        suite = get_suite("v1", suite_name)
        tools = {f.name: f for f in suite.tools}
        sinks = set(base.get("egress_sinks") or []) | set(base.get("integrity_sinks") or [])
        cls, drv = {}, {}
        for t, f in sorted(tools.items()):
            cls[t] = why[(suite_name, t)] if t in sinks else "benign"
            if t in sinks:
                props = f.parameters.model_json_schema().get("properties", {})
                drv[t] = sorted(a for a, p in props.items() if not is_rich(a, p))
        cfg = dict(base)
        cfg["consequence_overrides"] = cls
        cfg["max_unattended_consequence"] = "reversible"
        cfg["driving_args"] = drv
        cfg["floor_scope"] = "all_mutating"
        reads = sorted(t for t in tools if t not in sinks or t in (base.get("untrusted_sources") or []))
        private = sorted(t for t in tools if (t not in sinks or t == "get_unread_emails") and not PUBLIC.search(t))
        for name, extra in (("config_p10", None), ("config_p10s", private)):
            c = dict(cfg)
            if extra:
                c["sensitive_sources"] = sorted(set(c.get("sensitive_sources") or []) | set(extra))
            os.makedirs(os.path.join(HERE, name), exist_ok=True)
            with open(os.path.join(HERE, name, f"{suite_name}.yaml"), "w") as fh:
                fh.write(f"# config_rule_l2o/{suite_name}.yaml in proven polarity (residuals_rules.md\n"
                         f"# revision 10{', + item 2 secrets' if extra else ''}; derive_p10.py). Do not edit by hand.\n")
                yaml.safe_dump(c, fh, sort_keys=False)
        print(f"\n== {suite_name}")
        for t in sorted(sinks):
            old = base["driving_args"].get(t, [])
            print(f"  {t:32} {cls[t]:13} driving {drv[t]}" + (f"   (was {old})" if sorted(old) != drv[t] else ""))
        print(f"  secrets (+S): {private}")
        print(f"  public reads: {sorted(t for t in tools if t not in sinks and PUBLIC.search(t))}")


if __name__ == "__main__":
    main()
