# Eval tracker — ROPE comparison

Status of the runs that produce axor↔ROPE head-to-head evidence. Scope is the
ROPE comparison only; axor-only correctness/cost/latency runs (R0–R2, R4, R6,
R8–R11, and the write-then-read O2 probe) live in the full submission plan, not
here. Numbers we already hold live in `RUNS.md` + `README.md`.

**Legend:** ✅ done to spec · 🟡 partial / not to spec · ❌ not run.

**Baseline (plan invariant):** fixed positive-polarity build, STRICT,
`require_tool_roles=True`, commit hash pinned, per-task outcomes + raw
trajectories persisted.

**What we actually hold today:** three-suite ROPE head-to-head
(banking/slack/travel), agent = **gpt-4o-mini** via OpenRouter, ROPE AgentDojo
fork v1.2.2, attack = `important_instructions`, **1 pass**, soft (in-process)
boundary.

---

## Status matrix

| # | Prio | Item (ROPE arm) | Status | What we have | Gap vs spec | Owner |
|---|------|-----------------|--------|--------------|-------------|-------|
| R5 | P0 | **ROPE on InjecAgent** — the "what ROPE does not cover" evidence. Gate-check first (~60 consequence-only + ~50 DS); full DH+DS only if ROPE misses them | ❌ | — | not touched; gate-check not even run (needs the InjecAgent replay harness) | — |
| R3† | P0 | Adaptive / AutoDojo optimized attack run against **both** systems (ROPE repo's AutoDojo) | 🟡 | only **a2** catalogue-steering observed, and only across axor configs (travel any-trusted 12.9 vs request-only 7.1) | AutoDojo not stood up; ROPE never attacked adaptively; no GPT-4o closed loop | — |
| R7 | P1 | ROPE comparison multi-pass — Table 3 cells × 5 passes; **run banking ROPE attack ourselves**; gpt-4o-mini + gpt-4o; record router-cache origin | 🟡 | 3-suite ROPE compare, 1 pass | **1 pass not 5**; banking ROPE attack **not run ourselves** (published 0.0, footnote); no gpt-4o (Haoyu's ask open); router-cache origin not recorded | — |

† R3 here is only the ROPE-facing part (adaptive attack on both systems). The
rest of the adaptive suite (a1, a3–a7) is axor-only and lives in the full plan.

---

## Results we currently hold (R7, 1 pass) — CU / UA / ASR %

| Suite | undefended | axor | ROPE |
|---|---|---|---|
| banking | 56.2 / 43.1 / 54.2 | 43.8 / 40.3 / 0.0 | 50.0 / — / 0.0 ¹ |
| slack | 71.4 / 51.4 / 66.7 | 52.4 / 36.2 / 1.9 | 71.4 / 53.3 / 4.8 |
| travel (any-trusted) | 55.0 / 37.1 / 30.0 | 55.0 / 45.7 / 12.9 | 50.0 / 48.6 / 7.1 |
| travel (request-only) | — | 45.0 / 42.9 / 7.1 | 50.0 / 48.6 / 7.1 |

¹ ROPE banking attack not re-run — published number (R7 closes this by running it ourselves).

## Go / no-go (ROPE comparison)

Ready iff **R5** + **R7 to spec** + **R3† adaptive-on-both** are in hand.

- R5 — **not run** (blocks the headline "ROPE doesn't cover consequence" claim).
- R7 — present but **1 pass**, banking ROPE attack not self-run, no gpt-4o.
- R3† — only a2, on axor configs; ROPE not attacked adaptively.

**Current verdict for the ROPE comparison: NOT READY.**

## Results that can change the paper

- **R5:** if ROPE catches the consequence-only cases → drop that differentiation point.
- **R7:** if self-run banking ROPE attack ≠ published 0.0 → footnote becomes a measured cell.

## Suggested first run

**R5 gate-check** (≈1 day, cheapest decisive signal on the central thesis) →
then **R7 to spec** (5 passes, self-run banking ROPE attack, + gpt-4o) → then
**R3† AutoDojo on both systems**.
