# Revision 8 results — validity

Revision 8 (enum allowlist as a one-set L2 entry) was superseded by revision 9 before it
finished. The kernel worktree it ran on was switched to another branch at 07:06:28 UTC
while it was running, so:

- valid (finished before the switch): `residuals_ajar_attacks_rule8l2o_paper.json`
  (06:55–07:03), `rev8_breakdown_*` (07:02–07:04);
- not certain: `residuals_replay_rule8l2o_paper.json` (ended at about the switch);
- invalid, removed: `replay_live/rl_{v4,v5}_rule8l2o.json`, `rl_benign_rule8l2o_{a,b}.json`
  (started after the switch, ran on the operator_trusted kernel without the compilation);
- not produced: routes (stopped).

The `rev8_breakdown_*_rule_*` and `*_o_a` files are config_rule / config_rule_o runs and
do not depend on the revision-8 kernel change.
