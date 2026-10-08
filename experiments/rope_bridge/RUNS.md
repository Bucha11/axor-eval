# Run inventory

> For the ROPE-comparison run plan (R5 / R7 / adaptive-on-both) and what still
> has to run, see `EVAL_TRACKER.md`. This file records only what has already run.

What was actually evaluated for the axor↔ROPE banking/slack/travel comparison.
gpt-4o-mini agent via OpenRouter, ROPE's AgentDojo fork (v1.2.2), attack =
`important_instructions`. A "cell" = one task run (one `user_task` clean, or one
`user_task × injection_task` pair), each ≥1 model call.

## Suites

Three AgentDojo suites: **banking, slack, travel**. (AgentDyn suites — github,
shopping, dailylife — not yet run in this config.)

## axor (our bridge) — 1212 cells in the final logs

| Config | Suite | clean | attack |
|---|---|---|---|
| undefended | banking | 16 | 144 |
| as-run STRICT (GT allowlist) | banking | 16 | 144 |
| charged (consequence) | banking | 16 | 144 |
| origin (context, no allowlist) | banking | 16 | 144 |
| origin | slack | 21 | 105 |
| undefended | slack | 21 | 105 |
| origin | travel | 20 | 140 |
| undefended | travel | 20 | 140 |

## ROPE (their defense, same harness) — 302 cells

| Config | Suite | clean | attack |
|---|---|---|---|
| rope-opus (cached opus router) | banking | 16 | 0 (ASR 0.0 already reported) |
| rope-opus | slack | 21 | 105 |
| rope-opus | travel | 20 | 140 |

## Total

**1514 cells survive in the logs.** `force_rerun` overwrites in place, so several
iterations are not visible in the final logs:
- slack origin **before** the `get_channels` A3 fix (126) — overwritten post-fix;
- banking origin **misconfigured** attempts vs upstream (reads denied by the
  consequence gate, ~160) — overwritten once the full consequence map was added;
- per-run smokes (3–8 tasks each) before every full run.

Counting the overwritten re-runs, actual executed ≈ **1900–2000 cells**. Final
matrices (suite × config × {clean, attack}): 8 for axor + 3 for ROPE.

Results for these runs: see `README.md` (three-suite corrected table + per-IT
reading) and the banking config comparison. Reproduce numbers from the logs with
`axor_compare.py`.
