# Live preflight for c9v5 — GO/NO-GO (no model calls were made)

**Verdict: NO-GO as the harness stands.** Kernel, configs, model, tasks, budget and spend-cap are
ready; but the live executor does not yet wire the §9 reference view, the structured-output parser
(description grants), or the view-aware confirmer, and the per-episode logging and resume are
incomplete. Points 1,2,3,5,8 pass; 4,6,7 need harness work before launch.

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

## 4. References and the structured-output parser ON — NO (blocker)
The live executor (agentdojo_adapter.py:516) calls governor.register_output, NOT present_output, and
never calls observe_structured / observe_delegated or agent_args. So in a live run the model would
NOT see references (§9) and description grants (§9.15) would never mint — the config declares them,
but the executor does not exercise them. A faithful c9v5 live run needs the executor to: show the
model present_output (references in tool results), feed declared structured sources to
observe_structured/observe_delegated after each read, and keep evaluate (which already resolves
references). Until then the live run is c9v5-minus-§9, not c9v5.

## 5. Confirmation budget 5 per session — YES
run.sh sets AXOR_BENCH_L4_BUDGET=5; agentdojo_adapter._limited enforces it (asked>=budget →
over_budget, nothing asked), per task, with dedup of a refused call and an optional refusal cap.

## 6. Per-episode logging — PARTIAL
Logged today (_save_trajectory): suite, user_task_id, governed, utility, model, full message
trajectory, confirmations (count), l4 stats {asked, approved, refused, deduped, over_budget,
terminated} (budget-exhausted = over_budget>0 or terminated). NOT logged as structured fields: each
call's (tool, verdict, gate category) — a denial appears only as the tool-message error text; each
confirmer decision WITH the proposed call; per-episode tokens/cost (spend.jsonl is a global per-call
ledger, not attributed to an episode). Action: add a per-call decision record (tool, allowed,
category), a confirmer-decision log (proposed call + approved/refused + reason), and per-episode token
/ cost from the recorder. A mock-model dry run was not executed (no model, and these fields do not yet
exist to show); it should be run after the logging is added.

## 7. Hard $12 stop, checkpoints, resume — PARTIAL
Hard stop: YES — AXOR_BENCH_SPEND_CAP=12; _spend_guard sums the shared spend.jsonl before each call
and raises SpendCapReached (overshoot ≤ one call per process). Checkpoint: the shared spend.jsonl
persists the running total and per-task traj files are written as they finish, so a restart keeps
counting toward the cap. Resume from the break: NO — run_benign re-runs every USER_TASK
unconditionally (no skip-existing), so a restart repeats the whole suite/pass and spends again. Action:
skip a task whose traj file already exists.

## 8. Cost estimate — full A + B (view), the recorded design (3 passes, slack ut4 excluded)
575 episodes (A 287 + B 288), 2788 model calls at $0.00343/call (live_v4 mean $11.21/3267) ≈ **$9.57**,
under the $12 cap. Reusing the 179 no-flag episodes (live_reuse_c9v5.json) → re-run the 396 flagged
only ≈ **$6.06**. (If "581×3" means three fresh passes of all 581, that is ~$28.7 and would hit the
$12 cap mid-run.)
