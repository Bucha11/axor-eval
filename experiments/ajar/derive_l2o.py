"""Revision 8: config_rule_l2o/ = config_rule/ + value_policies (enum) built from O
(results/operator_o.json, revision 7) by the entity-class → argument table.

    python derive_l2o.py
"""
import json
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = {
    "banking": {"known payees": ["send_money.recipient", "schedule_transaction.recipient",
                                 "update_scheduled_transaction.recipient"]},
    "slack": {"users": ["send_direct_message.recipient", "add_user_to_channel.user", "remove_user_from_slack.user"],
              "channels": ["send_channel_message.channel", "add_user_to_channel.channel"]},
    "workspace": {("organisation addresses", "own-event participants"):
                  ["send_email.recipients", "send_email.cc", "send_email.bcc", "share_file.email",
                   "create_calendar_event.participants", "add_calendar_event_participants.participants"],
                  "own files": ["share_file.file_id", "append_to_file.file_id", "delete_file.file_id"]},
    "travel": {},
}


def main():
    o = json.load(open(os.path.join(HERE, "results", "operator_o.json")))
    os.makedirs(os.path.join(HERE, "config_rule_l2o"), exist_ok=True)
    for suite, table in MAP.items():
        cfg = yaml.safe_load(open(os.path.join(HERE, "config_rule", f"{suite}.yaml")))
        vp = {}
        for classes, targets in table.items():
            classes = classes if isinstance(classes, tuple) else (classes,)
            allowed = sorted({v for c in classes for v in o[suite]["O"][c]})
            for t in targets:
                tool, arg = t.split(".")
                assert arg in cfg["driving_args"].get(tool, []), (suite, t)
                vp.setdefault(tool, []).append({"arg": arg, "kind": "enum", "allowed": allowed})
        if vp:
            cfg["value_policies"] = vp
        with open(os.path.join(HERE, "config_rule_l2o", f"{suite}.yaml"), "w") as fh:
            fh.write(f"# config_rule/{suite}.yaml + value_policies from O (residuals_rules.md revision 8,\n"
                     "# derive_l2o.py). Do not edit by hand.\n")
            yaml.safe_dump(cfg, fh, sort_keys=False)
        print(suite, {t: [(p["arg"], len(p["allowed"])) for p in ps] for t, ps in vp.items()})


if __name__ == "__main__":
    main()
