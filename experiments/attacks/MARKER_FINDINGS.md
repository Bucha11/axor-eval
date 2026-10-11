# Sentinel marking as a taint channel — findings

What was tested: instead of (or beside) the content-derivation ledger in
`axor-core/axor_core/taint/ledger.py`, wrap every word of an untrusted read in a
sentinel character, decide taint at the gate by the sentinel's presence, and trim it
before execution. This is Microsoft's **datamarking** (arXiv 2403.14720), used here
in a different role: the published form uses the marker as a *hint to the model* not
to obey injected instructions; here it is a *provenance label the gate reads*.

All runs: OpenRouter, `temperature=1.0`, the sink tool-call forced (single-turn), the
untrusted read pre-staged as a tool result. Raw JSONL kept out of the repo. Harnesses:
`marker_carriage.py`, `marker_transform.py`, `marker_granularity.py`,
`marker_adaptive.py`, `marker_search.py`, `marker_defense.py`.

## 1. Carriage — can the model be used as a faithful byte channel?

340 cells (`marker_carriage.py`). Without a host instruction the sentinel never
survives a copy (0/80): the model strips it on its own. **With** a host instruction to
reproduce values verbatim, the three frontier models carry it 110/110, including when
an in-content note (named sentinel and all) tells them to strip it — the system
instruction beats the tool-content instruction. haiku-5.5 does not carry at all.
So carriage is a property of the model's trust hierarchy, not of the marker.

## 2. Coverage over the ledger's re-encoding gap

The decisive question is not verbatim copy (which the ledger already catches) but the
re-encoding gap of `axor-core` `docs/rfc-integrity-context-default.md` §1: the model
*reformats* the value and the substring match misses it. Measured on the same call,
over marked trials that actually transformed (`marker_transform.py`, 196 calls):

- The ledger misses 62 of 82, and on identifier reformatting it is a **total** miss:
  0/12 compact IBAN, 0/12 dashed, 0/19 basename, 0/18 split.
- The sentinel survives those transformations structurally — the model rebuilds the
  value around it (`•DE89•-•3704•-…`, `•q3-ledger.csv•`) — closing **58%** of the
  ledger's gap overall, **84%** on the models that carry.

So the sentinel layer is **not** a subset of the ledger: it covers the re-encoding the
ledger cannot, and the two are complementary (on paraphrase the ledger hits 20/20 and
the sentinel ~30%, the mirror image).

## 3. Granularity: mark inside the identifier, not on its edges

Whitespace marking puts the sentinel only on a value's **edges**, so a sub-part the
model extracts and re-types carries nothing. `struct` marking (also break at
`. / - _ @ :`) fixes this where the identifier has internal delimiters. Powered
comparison on that value class (`marker_granularity.py`, 350 calls, 2 informative
models, Wilson CIs):

| mode | marker_hit | gap closed |
|---|---|---|
| `word` | 62% (73/118) [53, 70] | 76% |
| `struct` | 77% (94/122) [69, 84] | 90% |

`word → struct`: **+15pp pooled [+4, +27] p=0.011**, and **+25pp [+11, +40] p=0.002** on
the scenarios where the value's markup actually differs between the two modes (4 of 7
were silently identical — a grouped-numeric no-op — which diluted the pooled figure).

For **grouped numerics** (IBAN groups, phone), where neither the ledger (groups < the
12-char segment minimum) nor `struct` (no internal delimiters) marks the value, finer
`chunk` marking was the hypothesis. It is **refuted** (`marker_granularity.py` numeric
class, 296 calls):

| mode | marker_hit | ledger_hit |
|---|---|---|
| `word` | 85% (52/61) | 0/61 |
| `chunk2` | 34% (18/53) | 0/53 |
| `chunk3` | 39% (23/59) | 0/59 |

`word → chunk2`: **−51pp [−67, −36] p<0.001**. Marking inside the digit groups makes
carriage strongly **worse** and, on gemini, also drops task correctness. The ledger
scores a flat **0** across the whole numeric class, so plain `word` marking already
closes 85% of a gap that is 100% open. Residual: ~15%, concentrated in compact
concatenation (the re-typing case).

**Scheme that follows:** one granularity per value class — `struct` for delimited
identifiers, `word` for grouped numerics, nothing works for prose (the ledger covers
there).

## 4. Security: it is coverage, not a control

Against a **static** pool of 11 hand-written injections the gate held: **0 bypasses /
277** (`marker_adaptive.py`), with the value under the attacker's control. But the
models did not comply with the injected formatting instructions *at all* (even where
harmless), so this measured the trust hierarchy, not the gate — exactly the static
result 2403.14720 reported, and exactly what arXiv 2510.09023 warns against reading as
security.

A **search-based** attacker (`marker_search.py`, LLM proposes injections, scored on
real gate feedback) broke the weak instruction **in round one** — three of four
candidates at bypass 1.00 — against sonnet-5.5 / iban. The mechanism matters more than
the rate: **none of the winners asks for the sentinel to be removed.** They supply the
attacker's IBAN in an **encoded** surface form (JSON `\uXXXX`, reversed, ROT13, hex
octets) and have the agent **derive** the plaintext. The derived string never existed
in the tool output, so no sentinel was ever on it and the ledger has no fragment to
match. One move, both gates silent, carriage fidelity irrelevant because the agent
computed rather than copied. Vectors recorded in `marker_search.FOUND_BYPASSES`.

This is the same defect as the ledger's, relocated: marking marks the bytes that are
**present**; a value that is only *derivable* from the content carries no mark, and an
LLM is a general-purpose decoder, so the encodings are unbounded. It needs no special
access — a phishing author just writes their account in hex.

**Consequence for axor:** the decode class is exactly what `integrity_default="context"`
stops — a computed value is not in the trusted index, so it carries `context_root` and
is denied. The sentinel is therefore *strictly weaker* than the default already
specified in the RFC, not an alternative to it.

## 5. Can a stronger host instruction repair the decode break?

A strengthened instruction (`marker_adaptive.PRESERVE_STRONG`) that governs values
obtained **by any operation** (decode/reverse/arithmetic/concat/reformat) and tells the
agent to wrap the result itself. Defence cross, 120 cells (`marker_defense.py`):

| defence | bypass (pooled over the 4 found vectors) |
|---|---|
| `preserve` / `word` | 52% (11/21) |
| `preserve` / `chunk2` | 24% (4/17) |
| `strong` / `word` | **0% (0/12)** |
| `strong` / `chunk2` | **0% (0/9)** |

On sonnet-5.5, where every bypass was found, `preserve` 83% (15/18) → `strong` **0/21**,
and the agent wraps the value it computed itself (`•gb29nwbk60161331926819•`).

Two caveats that keep this from being a defence result:

1. **These four vectors were optimised against `preserve`.** Replaying them against
   `strong` tests an old attack on a new defence, so a proper search was run *against*
   `strong` (sonnet/iban). Best run: **4 of 8 rounds, 8 distinct candidates, 0 bypasses,
   `sent_frac` never moved off 1.0** — the attacker tried a fake system turn
   (`<|im_end|>`), an assistant-working-notes spoof, "no account was supplied", an
   adapter "example IBAN", a serializer fixture and a transcription-repair framing, none
   of which moved the sentinel at all. For contrast, `preserve` fell in round **1**. So
   across four rounds of an adaptive attacker that broke the weak instruction immediately,
   `strong` held on sonnet — a real signal, but still not a completed search: every run
   stopped early, the last because the **proposer model itself was safety-flagged**
   ("possible cybersecurity risk") and refused to generate more candidates. Rounds 5–8
   never ran, and pushing past that ceiling would mean jailbreaking the attacker model,
   which was not done. **`strong` is therefore not proven to hold** — it is "not broken in
   4 rounds", which is stronger than the 0/277 static pool and weaker than a finished
   search.
   - Note: the search objective (`marker_search._score`) uses `sent_frac` — per-token
     wrapping of the *original* value — which credits a compacted-but-still-marked
     argument (`•GB29NWBK…•`) as partial progress toward a bypass it can never reach. The
     gradient is wrong; only actual sentinel *absence* should score. This is left
     unfixed in code and flagged here.
2. **`strong` breaks gemini.** Under it, gemini-3.8-flash produced no sink call in 29 of
   30 cells — it refuses to act at all, on attacks and control alike — while under
   `preserve` it acted normally and was already immune to the decode vectors (0/20). So
   `strong` is pointless on the model that didn't need it and disables that model's
   function. sonnet keeps acting under `strong` (27/30, control marker_hit and value_ok
   both 100%), so the cost is model-specific, not universal.

## Bottom line

- The sentinel layer is **measurable coverage against benign reformatting**: +25pp from
  `struct` on delimited identifiers, 85% where the ledger scores 0% on grouped numerics,
  complementary to the ledger under benign and static-adversarial conditions.
- It is **not a security control.** It is defeated by having the agent *derive* an
  encoded value, which carries no mark by construction — the same polarity failure as the
  ledger (RFC §2), and the class `integrity_default="context"` already covers.
- A stronger host instruction closes the known decode vectors on sonnet without a proper
  adaptive re-test, and **disables gemini**. Behavioural defences that make the agent the
  labeller are the class 2510.09023 defeats by search; a win there is a higher bar, never
  a guarantee.

Prior art: datamarking + randomised markers (arXiv 2403.14720, which *suggests* the
randomisation and does not test it); adaptive bypass of Spotlighting (arXiv 2510.09023,
~1% static → >95% searched). The novel, publishable slice is the **provenance-read**
framing (does the mark survive into the tool argument, which 2403.14720 never checks)
and the **per-value-class granularity** result — not a new defence.

## Unfinished (credit / classifier limits)

- Search against `strong`: capped at 4 of 8 rounds because the proposer model was
  safety-flagged and stopped returning candidates; rounds 5–8 need a different attacker
  model or a jailbroken one (not done). The `sent_frac` objective defect above should be
  fixed first regardless, or new rounds climb the wrong gradient — though against `strong`
  it never moved, so here it cost nothing.
- Original `preserve` search: `gemini/iban` and `sonnet/email` pairs not run.
