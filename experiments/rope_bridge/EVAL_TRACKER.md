# Eval tracker — camera-ready run plan (R0–R11)

Status of the submission run plan against what has actually been executed. This
is the single source of truth for "what still has to run before we submit"; the
numbers we already hold live in `RUNS.md` + `README.md`.

**Legend:** ✅ done to spec · 🟡 partial / not to spec · ❌ not run · 🔴 blocker.

**Baseline for every row (plan invariant):** fixed positive-polarity build, STRICT,
`require_tool_roles=True`, commit hash pinned in source of record, per-task
outcomes + raw trajectories persisted.

**What we actually hold today:** three suites (banking/slack/travel), agent =
**gpt-4o-mini** via OpenRouter, ROPE AgentDojo fork v1.2.2, attack =
`important_instructions`, **1 pass**, soft (in-process) boundary. Plus banking
charged/uncharged consequence axis, and the per-call latency bench.

---

## Status matrix

| # | Prio | Item | Status | What we have | Gap vs spec | Owner |
|---|------|------|--------|--------------|-------------|-------|
| **R3-a5** | P0 | **write-then-read: does a label survive storage** (`update_scheduled_transaction` → read) | 🔴 **BLOCKER** | nothing | never tested; if the label does not survive storage it is a hole in O2 and must be fixed before submission | — |
| R0 | P0 | Sanity: re-encoded IBAN (space/case/grouping/base64) → deny; unknown sink → deny | 🟡 | unknown-sink deny ✅; space/case/grouping caught by ledger (NFKC + edge-punct + segmentize), tests exist | **base64 NOT caught** (documented residual, not a deny); dedicated PoC run not done | — |
| R1 | P0 | AgentDojo cost, Table 2: 4 suites, 7 passes, undefended / request-only / any-trusted (+ banking request-only+supersession); `known_payees` rebuilt from env@t=0 | 🟡 | 3 suites; undefended + any-trusted; travel also request-only | model **gpt-4o-mini not o4-mini**; **1 pass not 7**; no workspace (4th suite); no banking request-only+supersession; oracle removed but `known_payees` not rebuilt from env@t=0 | — |
| R2 | P0 | ASR on capable models: GPT-4o + Qwen-72B, 4 suites, both settings, ≥3 passes | ❌ | — | entire cell; only gpt-4o-mini run | — |
| R3 | P0 | Adaptive suite closed loop a1–a7, GPT-4o | 🟡 1/7 | **a2** (catalogue steering IT4) = travel any-trusted 12.9 vs request-only 7.1 | no closed GPT-4o loop; **a5 blocker (above)**; a1/a3/a4/a6/a7 not run; AutoDojo not stood up | — |
| R4 | P0 | InjecAgent on fixed build (replay DH+DS 510, 2×2 origin×consequence; live governed loop GPT-4o+Qwen) | ❌ | — | dropped earlier ("забей на инжекагент") — reinstate or cut from plan | — |
| R5 | P0 | **ROPE on InjecAgent** — the "what ROPE does not cover" evidence (gate-check ~60 consequence-only + ~50 DS first) | ❌ | — | not touched; gate-check not even run | — |
| R6 | P0 | Benign cost floor: workspace+banking, realistic `sensitive_sources`, paired floor on/off, o4-mini, 7 passes | 🟡 | adjacent: banking charged-axis CU 62.5→43.8 | paired floor on/off on workspace+banking, o4-mini, 7 passes not done | — |
| R7 | P1 | ROPE comparison multi-pass: Table 3 cells × 5 passes; run banking attack ourselves; gpt-4o-mini + gpt-4o; record router cache origin | 🟡 | 3-suite ROPE compare | **1 pass not 5**; banking ROPE attack **not run ourselves** (published 0.0, footnote); no gpt-4o (Haoyu's ask open) | — |
| R8 | P1 | Allowlist sensitivity: ±k entries, gate replay + 1 live | ❌ | — | moved off oracle allowlist to origin config; k-perturbation not done | — |
| R9 | P1 | Real integration: LangGraph agent, 1 suite, undefended/governed, 3 passes; byte-identical verdicts vs shim on same intents | ❌ | — | entire cell | — |
| R10 | P1 | Latency on fixed build | ✅ | `axor-core/benchmarks/latency_gate.py`: trace off p99 78µs / ~28–32K checks/s vs PACT; trace on ~247–329µs / ~8K | — | done |
| R11 | P2 | Daemon boundary: verdict parity + overhead on 1 suite | ❌ | — | all runs on **soft boundary**; if not run, state so explicitly in the paper | — |

---

## Go / no-go

Plan criterion: ready iff **R1** + **R3 (≥ a1, a2, a4, a5)** + **R5** are in hand.

- R1 — present but **not to spec** (model, passes, 3/4 suites).
- R3 — only **a2**; **a5 untested** (blocker).
- R5 — **not run**.

**Current verdict: NOT READY.** Three of three go/no-go blocks are open; the most
dangerous is **R3-a5 (write-then-read)**. Fallback per plan: USENIX C2.

## Results that can change the paper

- **R5:** if ROPE catches the consequence-only cases → drop that differentiation point.
- **R3-a5:** if the label does not survive storage → hole in O2, fix before submission.
- **R1:** if `request-only` is catastrophically expensive → headline cost gets awkward but must still be shown.

## Suggested first run

**R3-a5** (cheapest decisive signal; resolves the blocker) — a focused
write-then-read probe on the existing banking bridge: taint a value, route it
through `update_scheduled_transaction`, read it back, assert the label survives
the store/read round-trip. Then **R5 gate-check** (≈1 day), then kick off **R1**
to spec (o4-mini, 4 suites, 7 passes) as the long background job.
