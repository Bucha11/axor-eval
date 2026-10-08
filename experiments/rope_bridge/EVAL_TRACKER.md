# Eval tracker — decisive runs (go / no-go)

Five runs decide whether there is a paper. Do them **in this order**: each next
run only matters if the previous one did not sink the paper. Everything else
(R3 adaptive on gpt-4o-mini, R6, R7, …) is an argument *inside* the paper, not
the question of whether the paper exists — see the bottom section.

Numbers we already hold: `RUNS.md` + `README.md`. Cost anchored to the real
spend so far (~$50 bought all runs to date on **gpt-4o-mini**); the decisive
block is ~$25, three of five runs free.

**Legend:** ✅ done · 🟡 partial · ❌ not run.
**Baseline:** fixed positive-polarity build, STRICT, `require_tool_roles=True`,
commit hash pinned, per-task outcomes + raw trajectories persisted.

---

## The decisive five (in order)

### 1. R0 — fix verification · free · ½ day · 🟡
Re-encoded IBAN (space / case / grouping) → **deny**; unknown sink → **deny**.
- **Gate:** if the fix does not hold, every later run is meaningless. Stop and fix.
- **Have:** unknown-sink deny ✅; space/case/grouping caught by ledger (NFKC +
  edge-punct + segmentize), tests exist. **base64 is a documented residual** (not
  a deny) — state it, don't run against it.

### 2. a5 — write-then-read · free · deterministic, no model · ❌
Through the governor, write an attacker value (`update_scheduled_transaction`),
then read it back with a trusted tool and inspect the label it gets.
- **Gate:** if the label is lost → **hole in O2, fix before anything else**.
- If it survives → this is the answer to review point **B3(ii)**.

### 3. R5 — ROPE gate-check on InjecAgent · ~$3 · ❌
Replay ROPE over ~60 consequence-only cases + ~50 data-stealing.
- **Decides positioning (a).** If ROPE catches the consequence-only + DS cases,
  the "what ROPE does not cover" thesis collapses — better to know before
  spending the remaining ~$97.

### 4. R1 — cost at `request-only` · replay free, live ~$15–20 · 🟡
The headline cost number.
- **Required by all four review sets; cannot submit without it**, whatever the
  other runs show.
- **Have:** travel any-trusted vs request-only, 1 pass (12.9 vs 7.1 ASR; CU 55→45).
  Need it as the proper cost headline (replay first, then one live pass).

### 5. R4 — InjecAgent 2×2 replay · free · an evening · ❌
Replay the 2×2 (origin × consequence) on InjecAgent.
- Closes the **0.6% vs 0.0%** discrepancy and **444 + 60 ≠ 510** (where 6 cases went).
- Not paper-deciding, but a reviewer spots the mismatch in 15 minutes — so close it.

**Decisive block total: ~$25** (R0, a5, R4 free; R5 ~$3; R1 ~$15–20 live).
After these four days: is O2 sound, is there a real ROPE difference, and what
does the guarantee cost. That is the whole go/no-go.

---

## After go/no-go — arguments inside the paper (not whether it exists)

| Run | What | Model | Rough $ |
|---|---|---|---|
| R3 adaptive | a1–a7 / AutoDojo robustness | **gpt-4o-mini** | ~$20–40 |
| R6 | benign cost floor (paired on/off) | gpt-4o-mini | ~$30–40 |
| R7 | ROPE comparison multi-pass, Table 3, self-run banking attack | gpt-4o-mini (+ gpt-4o only if Haoyu insists) | ~$150 on mini; +$1.5–2k if full gpt-4o ×5 |

All cheap on gpt-4o-mini. The only four-figure line anywhere is a **full gpt-4o
arm at 5 passes** (R7) — an optional cross-model validation, reducible to
~$50–100 on an attack-only / 1-suite / 2-pass subset. Not a default.

(R2, R8–R11 from the full submission plan are out of scope until the decisive
five clear.)
