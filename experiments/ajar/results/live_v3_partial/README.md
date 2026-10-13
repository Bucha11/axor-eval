# Live o4-mini, grants + L4, current rule — INCOMPLETE (stopped: OpenRouter credits)

Three governed passes were launched (config_rule with type matching, url, all_mutating,
access_control_sinks; L1+L2s+L4 oracle; L4 budget 5 = p99 of the earlier logs, dedup of
refused calls, no max-refusals). 217 of 291 task runs failed with OpenRouter 402
`in_flight_budget_exhausted` (the account had ~$2 of credit left while 21 processes ran
concurrently); 74 were graded. Spend $1.11. Not a measurement — kept for the record and
the trajectories (`trajectories.tgz`, one JSON per graded task).
