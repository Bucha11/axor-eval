# №2 v2 — live origin-only on c9v5 (re-run, grants genuinely off)

Re-run from scratch of #2 after the first attempt (`run_origin_c9v5.sh`) was found
contaminated: it set only `AXOR_BENCH_GRANT_LEVELS=""`, which does not strip the config's
own grant machinery, so that partial run still carried L1/L2 `grant_source` and
`grant_gate` denials (discarded → `results/live_origin_c9v5_contaminated/`).

## Setup (identical to A except grants)
- Protocol = A: o4-mini, `AXOR_BENCH_MAXTOK=4096`, CaMeL, `BENIGN_ONLY=1`, governed; 4 suites × 3 passes.
- Config: `config_m1_c9v5/<suite>.yaml` (unchanged vs A).
- Kernel: `axor_core == cad07bc` (via `--with-editable /home/user/core-m1`, the same source A's `run_c9v5.sh` uses — verified `git diff --quiet cad07bc HEAD -- axor_core/`).
- Origin-only: `AXOR_BENCH_NO_GRANTS=1` → `grant_ablation.strip_grants` (grant_args/grant_templates/grant_quotas/description/delegated/list stripped, `max_unattended_consequence` restored to CONSEQUENTIAL). `operator_sets`/`value_policies` kept (operator-set refusal is part of origin-only).
- Launcher: `final_live/run_origin_c9v5_v2.sh` (resumable across background time limits; the shared ledger enforces the $7 cap cumulatively).

## Completion
- `ALL_DONE` present; 12/12 (pass × suite) units rc=0.
- Spend **$4.6981** (cap $7, not reached).

## Grant-free verification (the point of v2)
Across **289 trajectories / 1018 governed calls**: **0 `grant_source`, 0 `grant_gate`**.
Decision categories — only the non-grant gates fire:

| category | count |
|---|---|
| approved | 927 |
| operator_set | 38 |
| reference_origin | 29 |
| consequence_gate | 17 |
| taint_enforcement | 5 |
| content_projection | 2 |

(Contrast — the discarded contaminated partial carried `grant_source` {L2:37, L1:20} and `grant_gate`:36.)

## Utility under origin-only governance (benign, across 3 passes)

| suite | utility | denials (non-grant gates) |
|---|---|---|
| banking | 21/48 | reference_origin 3, consequence_gate 11, taint_enforcement 2 |
| slack | 13/63 | operator_set 32, reference_origin 19, content_projection 2 |
| travel | 37/59 | — |
| workspace | 65/119 | taint_enforcement 3, reference_origin 7, operator_set 6, consequence_gate 6 |
| **TOTAL** | **136/289** | |

## Paths
- Results dir: `results/live_origin_c9v5_v2/` (per-suite logs, per-task trajectories with per-call `calls` decisions, `spend.jsonl`, `ALL_DONE`).
- Launcher: `final_live/run_origin_c9v5_v2.sh`.
- Discarded contaminated partial: `results/live_origin_c9v5_contaminated/` (gitignored, not committed).
