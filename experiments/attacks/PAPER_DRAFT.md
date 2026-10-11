# Marks that the model must carry: datamarking as a provenance label read at the tool-call boundary

**Draft — internal. Not for circulation.** All figures from `axor-eval/experiments/attacks`
(`marker_*.py`), OpenRouter, `temperature=1.0`, single-turn forced-sink harness. Raw
JSONL withheld from the repository.

## Abstract

Datamarking (Hines et al., arXiv:2403.14720) interleaves a sentinel character between
the words of untrusted text so a model can tell data from instructions. It was proposed
as a *prompting hint*: the marked text makes injected instructions easier for the model
to ignore. We repurpose the same construction as a *provenance label read by an
enforcement gate*: the host marks every untrusted read, a gate at the tool-call boundary
denies any argument that still carries the sentinel, and the sentinel is trimmed before
execution. The question is no longer "does marking reduce attack success" but "does the
mark survive onto the value the model actually places in a tool argument, and can an
enforcement decision rest on its absence." We measure carriage, coverage against a
content-derivation taint ledger, the effect of marking granularity, and adversarial
robustness, across four hosted models. We find the layer is **measurable coverage against
benign reformatting** — it catches identifier re-encodings a substring ledger cannot — but
**not a security control**: a search attacker defeats it in one round by supplying the
target value *encoded* and having the model *derive* the plaintext, which carries no mark
by construction. We report one positive, reproducible design result (marking at the
identifier's internal delimiters beats marking at word edges, +25pp, p=0.002) and one
negative one (finer within-token marking is worse, −51pp, p<0.001). We relate the decode
bypass to the known polarity failure of content-derivation taint and argue the construction
is strictly weaker than a context-default integrity gate that denies any value not provably
of trusted origin.

## 1. Setting

An LLM agent reads untrusted content (an inbox message, a web page, a tool result) and
later places values into tool calls, some of which are high-stakes sinks (a payment, an
email recipient, a file path, a shell command). The defender wants to deny any sink
argument whose value *originated in* untrusted content, while allowing values that
originated with the user or trusted configuration.

Two families of host-side mechanism exist. A **content-derivation ledger** registers
distinctive fragments of each untrusted read and, at a sink, flags an argument that
*contains* a registered fragment (this is the mechanism in `axor-core`
`axor_core/taint/ledger.py`). It is sound in the deny direction for verbatim copies but
blind to any re-encoding: a documented residual (`axor-core`
`docs/rfc-integrity-context-default.md` §1) is that a model which reformats an identifier
— compacting a grouped IBAN, lowercasing an address, taking a path's basename — slips past
the substring match. **Datamarking as a gate** is the alternative studied here: instead of
recognising the untrusted bytes at the sink, tag them at the source and look for the tag.

The pivot from the original datamarking work is the role of the mark. There, the model is
*asked* to treat marked text as data; success is measured as a drop in the model obeying
injected instructions. Here, the mark is a label the *gate* reads; success is the mark
being present on, or absent from, the specific value the model emits — a question
2403.14720 never evaluates, because its metric only inspects the model's completion for a
canary keyword, never the provenance of a tool argument.

## 2. Threat model and gate

The host controls the system prompt and the marking of tool outputs; it cannot control what
the model emits. The attacker controls the content of an untrusted read (they wrote the
inbox message) and wants a value of their choosing — their IBAN, their address, their
endpoint — to reach a sink in usable form. The gate denies a sink argument if **either**
(a) it carries the sentinel character, or (b) the ledger matches a registered fragment of
the read. An attack **bypasses** iff, over trials, the attacker's value reaches the sink
argument AND no sentinel is on it AND the ledger does not match AND the value is still
usable. All four conditions; laundering a value into an unusable form is not a win.

The host additionally instructs the model (system prompt) to reproduce copied values
verbatim, sentinels included. Two instruction strengths are studied:

- **`preserve`** — reproduce *copied* values exactly, sentinels included.
- **`strong`** — additionally govern any value *obtained by an operation* (decode, reverse,
  arithmetic, concatenation, reformatting, translation, reconstruction): the model must
  wrap the result itself, and tool content never overrides this whatever it asserts.

## 3. Method

Harness: the untrusted read is pre-staged as a tool result, the sink call is forced
(single-turn), so the measured quantity is carriage fidelity, not agent planning noise.
Marking modes: `word` (wrap each whitespace token — the sentinel lands on a value's edges),
`struct` (also split identifier-shaped tokens at `. / - _ @ :` and wrap each run — the
sentinel lands inside the identifier), `chunk<N>` (wrap every N characters). Models (via
OpenRouter): `claude-sonnet-5.5`, `openai/gpt-6.1-sol`, `google/gemini-3.8-flash`,
`claude-haiku-5.5`. Value classes: grouped-numeric (IBAN, phone), delimited identifier
(email, path, URL), and free prose. Adversarial search: an attacker model proposes
injection candidates, each is evaluated against the live gate, and the proposer is given
the gate's feedback and iterates (hill-climbing).

## 4. Carriage

Can the model be used as a faithful byte channel for the mark? (`marker_carriage.py`, 340
cells.) Without any host instruction the sentinel never survives a copy (0/80): the model
strips it unprompted. With the host instruction to preserve it, the three frontier models
carry it **110/110**, including when an in-content note names the sentinel and demands its
removal — the system instruction beats the tool-content instruction. `claude-haiku-5.5`
does not carry at all. **Carriage is a property of the model's instruction hierarchy, not
of the marker.** A corollary the rest of the paper depends on: the layer is only as present
as the model is willing to carry it, and that willingness is exactly what an attacker
contests.

## 5. Coverage over the ledger's re-encoding gap

A verbatim copy is the case the ledger already catches, so coverage must be measured where
the model *reformats* the value (`marker_transform.py`, 196 calls; the transformation is
demanded by the benign user task, not by an attacker). Over marked trials that actually
transformed:

- The ledger misses 62/82, and on identifier reformatting it is a **total** miss: 0/12
  compact IBAN, 0/12 dashed, 0/19 basename, 0/18 split field.
- The sentinel survives those transformations structurally — the model rebuilds the value
  around it (`•DE89•-•3704•-…`, `•q3-ledger.csv•`) — closing **58%** of the ledger's gap
  overall and **84%** on the models that carry.

Coverage is complementary in both directions: on paraphrase the ledger hits 20/20 (a long
common token matches) while the sentinel reaches ~30%. So the sentinel layer is **not a
subset** of the ledger; the two cover different failure shapes of the same benign
reformatting.

## 6. Granularity is a per-value-class choice

Word marking puts the sentinel on a value's **edges**, so a sub-part the model extracts and
re-types carries nothing. For identifiers with internal delimiters, `struct` marking fixes
this. Powered comparison on that class (`marker_granularity.py`, 350 calls, two informative
models, Wilson 95% CIs):

| mode | marker survives | ledger's gap closed |
|---|---|---|
| `word` | 62% (73/118) [53, 70] | 76% |
| `struct` | 77% (94/122) [69, 84] | 90% |

`word → struct`: **+15pp pooled, 95% CI [+4, +27], p=0.011**; and **+25pp [+11, +40],
p=0.002** restricted to scenarios where the value's markup actually differs between the two
modes (4 of 7 scenarios were a silent no-op for `struct` and diluted the pooled figure).
The gain concentrates in sub-part extraction: `path_basename` 67%→100%, `url_compose`
42%→69%, `email_domain` 88%→100%.

For grouped numerics, where neither the ledger (groups below the 12-char fragment minimum)
nor `struct` (no internal delimiters) marks the value, finer within-group marking was the
hypothesis. It is **refuted** (296 calls):

| mode | marker survives | ledger hit |
|---|---|---|
| `word` | 85% (52/61) | 0/61 |
| `chunk2` | 34% (18/53) | 0/53 |
| `chunk3` | 39% (23/59) | 0/59 |

`word → chunk2`: **−51pp, 95% CI [−67, −36], p<0.001**. Marking inside the digit groups is
strongly worse and, on one model, also degrades task correctness. The ledger scores a flat
**zero** across the entire numeric class, so plain `word` marking already closes 85% of a
gap that is 100% open; the residual (~15%) is compact concatenation, the re-typing case.

**Design rule.** One granularity per value class — the coarsest that still marks the pieces
the model keeps: `struct` for delimited identifiers, `word` for grouped numerics, and
nothing for prose (where the ledger covers instead). This is a positive, reproducible result
and, with the provenance-read framing, the paper's novel contribution; it is not a new
defence.

## 7. Adversarial evaluation

**Static pool.** Eleven hand-written injections (name the sentinel, frame it as display
artefact / relay corruption / disabled annotation, assert the destination rejects
non-alphanumerics, request base64 or spell-out), value under attacker control: **0 bypasses
/ 277** (`marker_adaptive.py`). But the models declined the injected formatting instructions
*wholesale*, even harmless ones, so this measures the instruction hierarchy, not the gate —
the static result of 2403.14720, and exactly the reading arXiv:2510.09023 warns against.

**Search.** An LLM attacker scored on live gate feedback breaks `preserve` **in round one**
against `claude-sonnet-5.5` (three of four candidates at 100% bypass). The mechanism is the
paper's central negative result and **does not strip the sentinel**: the attacker places the
target value in the content *encoded* — JSON `\uXXXX` escapes, the string reversed, ROT13
with a digit shift, hex ASCII octets — and instructs the model to *derive* the plaintext.
The derived string never appeared in the tool output, so no sentinel was ever on it and the
ledger has no fragment to match. One move, both gates silent, and the model's (perfect)
carriage fidelity is irrelevant because it computed the value rather than copying it.
Vectors in `marker_search.FOUND_BYPASSES`.

**Can `strong` repair it?** Defence cross against the four found vectors
(`marker_defense.py`, 120 cells):

| defence / marking | bypass (pooled over 4 vectors) |
|---|---|
| `preserve` / `word` | 52% (11/21) |
| `strong` / `word` | **0% (0/12)** |
| `strong` / `chunk2` | **0% (0/9)** |

On `claude-sonnet-5.5`, where all bypasses were found: `preserve` 83% (15/18) → `strong`
**0/21**, with the model wrapping the value it computed itself (`•gb29nwbk60161331926819•`).
But (a) those vectors were optimised against `preserve`, so this is an old attack on a new
defence, and (b) `strong` **disables** `google/gemini-3.8-flash`, which then declined the
sink in 29/30 cells — on attacks and benign control alike — while under `preserve` it acted
normally and was already immune to the decode vectors (0/20). The repair's cost is
model-specific.

A proper search *against* `strong` (`claude-sonnet-5.5`, 8 rounds planned) was run with two
independent attacker models. `openai/gpt-6.1-sol`: **4 rounds, 8 candidates, 0 bypasses**,
sentinel never moved (fake system turn, assistant-working-notes spoof, "no account supplied",
adapter example value, serializer fixture, transcription-repair), stopped when the proposer
was **safety-flagged**. `z-ai/glm-5.3-prime`: 4 rounds / 12 candidates
before a reasoning-budget truncation, then — reasoning capped to `effort=low` and resumed
from that memory — **6 further rounds to completion** (`ended: exhausted`), for **10 rounds,
30 candidates, 0 bypasses**, sentinel never moved (same-day-urgency, ERP keying card, "check
digits are never transmitted on this channel", a spoofed "integrity protocol v2" notice, a
sandbox smoke-test, a voicemail transcription, a desk read-back). Across both attackers, ~38
distinct candidates, 0 bypasses, the sentinel never moved once; the GLM search is the first
to run to completion rather than stop on a proposer-side failure. `strong` held every round.
A genuinely strong negative result on this model/target — above the static 0/277 — but still
one defender model, one value class, one seed, and an LLM-rewriting optimiser weaker than the
gradient-free and human attackers of 2510.09023: **"not broken by a completed 6-round GLM
search plus a 4-round gpt search", not proof it holds in general.**

## 8. Discussion

Marking labels the bytes that are **present**. A value that is only *derivable* from the
content carries no mark, and an LLM is a general-purpose decoder, so the space of encodings
is unbounded. This is the **same polarity failure** as the content ledger's (RFC §2),
relocated rather than repaired: the gate is a blocklist of surface forms, and the default
for an unrecognised form is "clean". It needs no special access — a phishing author writes
their account number in hex. A context-default integrity gate inverts the polarity (deny any
value not *provably of trusted origin*); a computed value is not of trusted origin, so it is
denied regardless of how it was encoded. The sentinel layer is therefore **strictly weaker**
than that default, not an alternative to it. Its defensible role is coverage against *benign*
reformatting — raising the ledger's recall on honest agents — and, in the near-binary
carriage statistic, a channel canary (verify at runtime that a known marked value returns
marked before trusting an absence).

## 9. Limitations

- **The strong instruction is not adversarially settled.** The search against it ran 4 of 8
  rounds; rounds 5–8 require an attacker model that is not safety-gated, or a jailbroken one,
  neither used here.
- **Search objective defect.** The hill-climb's graded objective credits `sent_frac` (per-token
  wrapping of the *original* value), so a compacted-but-still-marked argument scores as partial
  progress toward a bypass it cannot reach. The gradient should reward sentinel *absence* only.
  Against `strong` the sentinel never moved, so the defect cost nothing there; against
  `preserve` a bypass was found in round one without needing the gradient. It should be fixed
  before any run where partial stripping is the expected path.
- **Scope.** Four hosted models, English, single-turn forced sink; no multi-hop (context
  compression, sub-agent spawn), where each hop is a further chance to lose the mark; token
  cost not measured.
- **Lower bound only.** The search is a few rounds of LLM rewriting — weaker than the
  gradient-free optimisers and human red-teamers of 2510.09023, which took this mechanism from
  ~1% static to >95% searched.

## 10. Related work

Spotlighting / datamarking (Hines et al., 2403.14720) — the construction, used as a prompting
hint, with randomised markers *suggested but not tested*; we test the read-at-the-gate role it
does not. "The Attacker Moves Second" (Nasr, Carlini et al., 2510.09023) — adaptive search
defeats Spotlighting among 12 defences (~1%→>95%), the result our decode bypass instantiates on
a provenance gate. CaMeL, FIDES, and argument-provenance surveys — host-side taint that does not
depend on the model carrying anything; the context-default integrity RFC in `axor-core` is the
gate we argue dominates marking.

## 11. Conclusion

Used as a provenance label read at the tool-call boundary, datamarking is measurable coverage
against benign reformatting and a complement to a content ledger, with one clean design rule
(mark at the identifier's internal delimiters; coarser for grouped numerics; never finer). It
is not a security control: an attacker defeats it by having the model derive an encoded value,
which carries no mark by construction — the same failure that motivates context-default
integrity, which the marking layer is strictly weaker than. A stronger host instruction closes
the known decode vectors on one model without a completed adaptive re-test and disables another.
The reproducible contributions are the provenance-read framing and the per-value-class
granularity result; the security claim is negative.
