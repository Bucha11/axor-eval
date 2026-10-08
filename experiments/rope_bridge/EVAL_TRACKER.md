# Eval tracker — ROPE run

From the decisive go/no-go plan, the only run with a ROPE arm.
(The axor-only decisive runs — R0 fix-check, a5 write-then-read, R1
request-only cost, R4 InjecAgent replay — are tracked in the full submission
plan, not here.) Held numbers: `RUNS.md` + `README.md`.

**Baseline:** fixed positive-polarity build, STRICT, `require_tool_roles=True`,
commit hash pinned, per-task outcomes + raw trajectories persisted.

---

## R5 — ROPE gate-check on InjecAgent · ~$3 · ❌ not run
Replay ROPE over ~60 consequence-only cases + ~50 data-stealing.
- **Decides positioning (a).** If ROPE catches the consequence-only + DS cases,
  the "what ROPE does not cover" thesis collapses — know this before spending
  anything else.
- Full DH+DS on the same models only if the gate-check shows ROPE misses them.
- **Can change the paper:** ROPE catching these → drop that differentiation point.

**Status:** not run. Needs the InjecAgent replay harness + the ROPE clone
(scratchpad, likely reaped — re-clone if gone).
