# Live c9v5 — paid run (A + B view-aware), FROZEN kernel

Paid live run on the **frozen c9v5** kernel (axor-core `claude/model-m1` 618c4a9) and the frozen
configs `config_m1_c9v5/` (FREEZE_C9V5.md). Live harness 83dee51 (references / description grants /
view-aware confirmer / per-episode logging / resume). Model openai/o4-mini via OpenRouter, CaMeL mode,
**benign only** (no injections), governed condition, 3 passes × 4 suites. slack user_task_4 excluded in
analysis (as in live_v4). Shared spend ledger, hard cap $12.

Two configurations:
- **A** = grant level **L1** (no human in the loop; `AXOR_BENCH_L4_CONFIRM=oracle` but L4 budget is
  not used — A never asks).
- **B** = **L1 + L4** with the **view-aware** confirmer (`AXOR_BENCH_L4_CONFIRM=view`, budget 5): a
  call the grant gate would refuse is confirmed only if the tool's verb is in the request AND every
  destination value it names is in the request.

## Utility (288 episodes each = 96 tasks × 3 passes)

| config | pass1 | pass2 | pass3 | overall |
|---|---|---|---|---|
| A (L1) | 53/96 = 0.552 | 52/96 = 0.542 | 53/96 = 0.552 | **158/288 = 0.549** |
| B (L1+L4 view) | 60/96 = 0.625 | 62/96 = 0.646 | 57/96 = 0.594 | **179/288 = 0.622** |

By suite (overall over 3 passes):

| config | banking | slack | travel | workspace |
|---|---|---|---|---|
| A | 24/48 = 0.500 | 28/60 = 0.467 | 38/60 = 0.633 | 68/120 = 0.567 |
| B | 32/48 = 0.667 | 30/60 = 0.500 | 38/60 = 0.633 | 79/120 = 0.658 |

B lifts utility over A by **+0.073** (0.549 → 0.622): the view-aware L4 recovers benign calls the
pure L1 grant gate refuses, and does so without any attacker present to exploit it.

## Confirmations (B only; A never asks)

- L4 **asked = 60**, **approved = 21**, **refused = 39**, deduped/over-budget = 0.
- budget_exhausted episodes = 0 in both A and B (the budget-5 ceiling was never hit).

So B's +21 benign calls over A's grant gate come at the cost of 60 confirmation prompts across 288
episodes (≈ 0.21 prompts/episode); 39 of those prompts the view confirmer itself refused.

## Landed attacks

**0 — by construction.** This is a benign run: every episode has `injection_task_id = null` and no
injections are loaded, so there is no attacker call to land. (Attack resistance for c9v5 is measured
in the 1887 replay and the Ajar attacks column, `results/final_numbers_c9v5.md`, not here.)

## Spend

- Ledger total (shared `spend.jsonl`): **$9.6315** over **2771** model calls, under the $12 cap.
- Of that, recorded per-episode trajectory cost: A $4.8866 + B $4.5606 = $9.4472 (the ~$0.18
  remainder is calls logged to the ledger during episodes whose trajectory was later resumed/rewritten
  across the two 2h-limit restarts; the ledger is the authoritative total).

Run executed serially with two automatic restarts (both prior background jobs hit the 2h limit);
resume skipped every completed trajectory and the shared ledger preserved the cap accounting, so no
episode was paid for twice. All 6 passes completed (6 × 97 trajectories written; 96 analyzed after the
slack user_task_4 exclusion). `ALL_DONE` present, final shell rc=0.
