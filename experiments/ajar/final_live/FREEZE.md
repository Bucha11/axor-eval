# Freeze — final live run (o4-mini), fixed before any paid call

| item | value |
|---|---|
| axor-core kernel | branch claude/model-m1, commit 1ab3a2dbfb790e75541e61c03b000fbbfb57551a |
| kernel tree clean | yes |
| runner | examples/agentdojo/run_agentdojo.py sha256 0ffcef4c2c47458c |
| adapter (L4 oracle, limits, spend) | examples/agentdojo/agentdojo_adapter.py sha256 9e800005d351a055 |
| config banking | config_m1_content/banking.yaml sha256 e2c13e45cb83639d |
| config slack | config_m1_content/slack.yaml sha256 021f74caa2f083aa |
| config travel | config_m1_content/travel.yaml sha256 1ae97935b3ed145f |
| config workspace | config_m1_content/workspace.yaml sha256 00a7c6e463efa60e |
| model | openai/o4-mini via OpenRouter, max_tokens 4096 (as the undefended passes: completions reach 4096 in spend_undef.jsonl) |
| AgentDojo | agentdojo==0.1.35, suites v1, benign axis, all user tasks |
| integrity | from the config: context default, request-only origins (the runner sets no override) |
| (A) | AXOR_BENCH_GRANT_LEVELS=L1 — no confirmer: an unproven call is refused |
| (B) | AXOR_BENCH_GRANT_LEVELS=L1+L4 — the live oracle (approves iff the call's grant args, = the final driving args, equal a ground-truth call's), L4 budget 5 per task, refused calls deduplicated |
| passes | 3 per configuration, paired with undefended passes 1–3 (EXCLUSIONS.md) |
| spend cap | $12.00 total, smoke included; guard: stop at > 5% errored tasks |
