# Re-run of the episodes changed by MODEL.md §8.14 — fixed before the run

| item | value |
|---|---|
| kernel | axor-core claude/model-m1 09e98af (8883c43 + AXOR_BENCH_USER_TASKS) |
| run_agentdojo.py | sha256 d623aad4508ba52f |
| agentdojo_adapter.py | sha256 9e800005d351a055 (unchanged from FREEZE.md) |
| config banking | config_m1_c814/banking.yaml sha256 21295bcd4cf3455a |
| config slack | config_m1_c814/slack.yaml sha256 8e16858b34a311ad |
| config travel | config_m1_c814/travel.yaml sha256 63b40195e012386d |
| config workspace | config_m1_c814/workspace.yaml sha256 7a5140ed0b2307bd |
| model, agentdojo, max_tokens, L4 budget | as FREEZE.md (o4-mini via OpenRouter, 0.1.35 v1, 4096, 5) |
| spend | results/live_final/rerun814/spend.jsonl, cap $2.00 |

Episodes: those whose recorded decisions differ between the final config and config_m1_c814 with
a changed verdict (final_live/decisions_live.py; results/live_final_decisions_*.json), all workspace:

| config | pass | user tasks |
|---|---|---|
| A | 1 | 25 |
| A | 2 | 19, 25 |
| A | 3 | 25 |
| B | 1 | 13, 19, 25, 31 |
| B | 2 | 13, 25 |
| B | 3 | 19, 25 |

Not re-run: the 6 A episodes changed by §8.13 only in the refusal's category (banking 12, 15).
Analysis: each re-run episode replaces its original in its pass; every other episode is kept;
pairing and exclusions as EXCLUSIONS.md. A re-run episode that raises counts as a failure. Nothing
is re-run again after seeing the results.
