# Live preflight for c9v5 — GO/NO-GO (no model calls were made)

**Verdict: GO (pending the user's launch word).** All eight points pass after the live-harness fixes
(commit 83dee51, examples/agentdojo only; governance axor_core/ unchanged, c9v5 freeze holds). The
preflight script now PASSES (governance unchanged vs 618c4a9, live-harness hashes and configs match).

## 1. Hash check at start, stop on mismatch — YES (script added: preflight_c9v5.py)
`python final_live/preflight_c9v5.py` hashes the kernel commit, the four c9v5 configs and the harness
against FREEZE_C9V5.md and exits non-zero on any mismatch. Current output: kernel 618c4a9 OK, all four
configs OK, axor_ajar.py MISMATCH (ba003636… vs frozen ab0444ed…).
- The mismatch is expected and harmless to the live run: axor_ajar.py changed after the freeze only by
  adding `_CONSEQ_CEIL` and `max_unattended_consequence=_CONSEQ_CEIL` INSIDE the `no_grants` block
  (git diff a22077b), which runs only for the offline origin-gate-only path (AxorDefense no_grants);
  the "view" wiring is in decisions_live.py (offline shadow). The LIVE run uses
  core-m1/examples/agentdojo/{run_agentdojo.py,agentdojo_adapter.py}, covered by the kernel commit
  618c4a9 — it never imports axor_ajar.py or AxorDefense. So A and B live decisions are unchanged;
  the only intended behavioural change for B is the view-aware confirmer, which is additive.
- Action before launch: re-freeze the harness hashes to name the LIVE harness
  (run_agentdojo.py/agentdojo_adapter.py) so the preflight gate is meaningful, or record the current
  axor_ajar.py hash with the diff noted.

## 2. Model string and parameters — YES
Recorded live_v4 trajectories store model = "openai/o4-mini"; spend.jsonl records the same. run.sh
sets AXOR_BENCH_MODEL=openai/o4-mini, AXOR_BENCH_MAXTOK=4096 — identical to the reused undefended
passes. (OpenRouter resolves the exact o4-mini snapshot server-side; the string pinned is
openai/o4-mini, as in the reused records.)

## 3. Tasks — YES
CAMEL_MODE uses every user task of the four suites (banking 16 + slack 21 + travel 20 + workspace 40
= 97; slack user_task_4 excluded → 96). AgentDojo 0.1.35, v1 suites (run.sh: --with agentdojo==0.1.35;
get_suite("v1", …)). Same as the reused passes.

## 4. References and the structured-output parser ON — YES (fixed, commit 83dee51)
The governed executor now returns present_output as the tool result the model sees (references, §9),
and feeds each read's parsed structure to observe_structured / observe_delegated (description grants,
§9.15/§9.16) via _parse_structured (the same formats as the offline axor_ajar.structured). Proof —
the mock dry run (no model, results/mock_dry_run_c9v5.txt): slack user_task_7 add_user_to_channel is
admitted via an L1 grant with description "channel starting with External" = ['External_0'], i.e. the
description grant minted from the observed get_channels structure.

## 5. Confirmation budget 5 per session — YES
run.sh sets AXOR_BENCH_L4_BUDGET=5; agentdojo_adapter._limited enforces it (asked>=budget →
over_budget, nothing asked), per task, with dedup of a refused call and an optional refusal cap.

## 6. Per-episode logging — YES (fixed, commit 83dee51)
_save_trajectory now writes, per episode: suite, user_task_id, governed, utility, model, full
trajectory, calls [{tool, allowed, category, grant_source, description}] (per-call verdict and gate),
l4 stats {asked, approved, refused, deduped, over_budget, terminated}, l4_decisions [{call, approved,
policy}] (each confirmer decision with the proposed call), budget_exhausted (over_budget or
terminated), and cost_usd (this episode's spend-ledger delta). The mock dry run
(results/mock_dry_run_c9v5.txt, no model) shows the calls / l4_stats / l4_decisions / confirmations
fields populated for three episodes.

## 7. Hard $12 stop, checkpoints, resume — YES (fixed, commit 83dee51)
Hard stop: YES — AXOR_BENCH_SPEND_CAP=12; _spend_guard sums the shared spend.jsonl before each call
and raises SpendCapReached (overshoot ≤ one call per process). Checkpoint: the shared spend.jsonl
persists the running total and per-task traj files are written as they finish. Resume: run_benign now
skips a task whose trajectory file already exists (reusing its recorded utility), so a restart
continues from the break instead of re-running and re-spending.

## 8. Cost estimate — full A + B (view), the recorded design (3 passes, slack ut4 excluded)
575 episodes (A 287 + B 288), 2788 model calls at $0.00343/call (live_v4 mean $11.21/3267) ≈ **$9.57**,
under the $12 cap. Reusing the 179 no-flag episodes (live_reuse_c9v5.json) → re-run the 396 flagged
only ≈ **$6.06**. (If "581×3" means three fresh passes of all 581, that is ~$28.7 and would hit the
$12 cap mid-run.)
