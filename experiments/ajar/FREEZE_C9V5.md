# c9v5 frozen (MODEL.md 9.18 + 9.19 + 9.20/9.20a)

| item | value |
|---|---|
| kernel | axor-core claude/model-m1 618c4a9 |
| config banking | config_m1_c9v5/banking.yaml sha256 4ed005685fbc6828 |
| config slack | config_m1_c9v5/slack.yaml sha256 45564b9f656b1e47 |
| config travel | config_m1_c9v5/travel.yaml sha256 695459e1dbbb2ec8 |
| config workspace | config_m1_c9v5/workspace.yaml sha256 23abdaeed0979f35 |
| harness | axor_ajar.py sha256 ab0444ed02cebedd |

c9v5 = c9v4 + 9.18 (O addresses = user domain + addresses the user wrote to) + 9.19 (named sender unique) + 9.20/9.20a (list arg elements in clause literals ∪ O; relax only the list arg of a grant with an L1 ground). Ajar b 61/92, c-oracle 92/92, attacks 1/609; benign 288 without a human 216; replay 1887 landed 7; route 2 no injected value admitted, k unchanged. L1 +4 vs c9v5 without 9.20 (own cc/bcc of travel 3) accepted. Not changed after this point; any further rule is a new configuration.
