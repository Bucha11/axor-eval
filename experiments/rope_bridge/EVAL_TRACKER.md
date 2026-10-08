# Eval tracker — ROPE comparison

Only the runs that produce axor↔ROPE head-to-head evidence. axor-only go/no-go
runs (R0 fix-check, a5 write-then-read, R1 request-only cost, R4 InjecAgent
replay) and axor-only in-paper runs (R6) are tracked in the full submission
plan, not here. Numbers we already hold: `RUNS.md` + `README.md`.

**Legend:** ✅ done · 🟡 partial · ❌ not run.
**Baseline:** fixed positive-polarity build, STRICT, `require_tool_roles=True`,
commit hash pinned, per-task outcomes + raw trajectories persisted.
**Cost anchor:** ~$50 bought all runs to date on **gpt-4o-mini**; the ROPE block
is cheap on mini — the only four-figure line is an optional full gpt-4o arm.

---

## R5 — ROPE gate-check on InjecAgent · ~$3 · ❌ · DECISIVE
Replay ROPE over ~60 consequence-only cases + ~50 data-stealing.
- **Decides positioning (a).** If ROPE catches the consequence-only + DS cases,
  the "what ROPE does not cover" thesis collapses — know this before spending
  anything else. Run this first; the rest of the ROPE block only matters if it
  survives.
- Full DH+DS on the same models only if the gate-check shows ROPE misses them.

## R3† — adaptive / AutoDojo attack on both systems · ~$20–40 (mini) · 🟡
Run the ROPE repo's AutoDojo optimized attack against **both** axor and ROPE.
- **Have:** only **a2** catalogue-steering observed, and only across axor configs
  (travel any-trusted 12.9 vs request-only 7.1). AutoDojo not stood up; ROPE
  never attacked adaptively.
- (The axor-only cells of the adaptive suite — a1, a3–a7 — live in the full plan.)

## R7 — ROPE comparison multi-pass · ~$150 (mini) · 🟡
Table 3 cells × 5 passes; **run the banking ROPE attack ourselves**; record
router-cache origin; add gpt-4o only if Haoyu insists.
- **Have:** 3-suite ROPE head-to-head, 1 pass (table below).
- **Gap:** 1 pass not 5; banking ROPE attack not self-run (published 0.0,
  footnote); no gpt-4o; router-cache origin not recorded.
- **Cost:** ~$150 on gpt-4o-mini. A **full gpt-4o arm ×5 passes is +$1.5–2k** —
  optional cross-model validation, reducible to ~$50–100 on an attack-only /
  1-suite / 2-pass subset. Not a default.

### Held result (R7, 1 pass) — CU / UA / ASR %
| Suite | undefended | axor | ROPE |
|---|---|---|---|
| banking | 56.2 / 43.1 / 54.2 | 43.8 / 40.3 / 0.0 | 50.0 / — / 0.0 ¹ |
| slack | 71.4 / 51.4 / 66.7 | 52.4 / 36.2 / 1.9 | 71.4 / 53.3 / 4.8 |
| travel (any-trusted) | 55.0 / 37.1 / 30.0 | 55.0 / 45.7 / 12.9 | 50.0 / 48.6 / 7.1 |
| travel (request-only) | — | 45.0 / 42.9 / 7.1 | 50.0 / 48.6 / 7.1 |

¹ ROPE banking attack not re-run — published number (R7 closes this by running it ourselves).

---

## Order & verdict
**R5 gate-check first** (~$3, decides the central thesis) → if it survives, **R7
to spec** (5 passes, self-run banking attack, mini) → **R3† AutoDojo on both**.
Whole ROPE block ~$175 on gpt-4o-mini; gpt-4o only on Haoyu's insistence.

**Current verdict:** NOT READY — R5 not run, R7 only 1 pass, R3† only a2.

**Can change the paper:** R5 — if ROPE catches consequence-only + DS, drop that
differentiation. R7 — if self-run banking ROPE attack ≠ published 0.0, the
footnote becomes a measured cell.
