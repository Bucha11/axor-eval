# One model, fixed rules: how an axor deployment is described

## 0. Why

Every failure of the last revisions was of one kind: the configuration was a dozen independent
lists (sources, secrets, sinks, driving args, classes, allowlists, templates, shared stores,
audience, destination and content args) and nothing checked that they agreed — O was empty, L2 had
no tie to the allowlist, `delete_file` had the wrong class, "every argument is driving" broke
things the lists did not foresee. Here the operator describes two things about the deployment —
**who is who** (the entity model) and **what each tool does** (the tool model) — and every list
the kernel reads is compiled from them by **fixed, general rules** (§3). The rules are the same
for every deployment; only the two models change. `derive_model.py` is that compiler; it writes
the kernel's current config format (`config_model/`), so the kernel is unchanged.

## 1. Entity model — who is who, who sees what

Derived from the deployment's initial state by a fixed procedure (structured fields only — never
a message body, a web page, a file's content, a received mail's sender or the inbox contact list,
all attacker-writable):

| class | AgentDojo source |
|---|---|
| the user's own identifiers | account IBAN (banking), account e-mail (travel, workspace) |
| payees | recipients of the user's own outgoing and scheduled transactions |
| members, channels | slack users; channels except those named `External_*` |
| organisation addresses | addresses with the user's domain in a structured field, ∪ participants of the user's own events |
| own objects | files the user owns; events in the user's calendar that list the user; mails the user sent |
| viewers of an object | a file's `shared_with`, an event's other participants |

**Own** = the union of the classes above; it is O, the *audience* of a secret, and the source of
the L2 templates.

**1.3 Mandatory check.** No own entity may be an attacker entity. `derive_model.py` separates the
attacker-**controlled** identifiers (what an injection brings in: its e-mail, IBAN, URL, a user it
invites) from the attacker-**targeted** own entities (a member it messages). AgentDojo: controlled ∩
own = ∅ in all four suites; targeted: slack Alice (injection 1) and the channels general / private
/ random (injections 2, 4, 5) — legitimate members the attacks aim at, kept as own and reported;
workspace "13" (injection 1 deletes *file* 13; the user's *event* 13 is own) — a collision of id
namespaces, not a shared entity. Enforcement is per (tool, argument), so `delete_file.file_id` sees
only own files; but the kernel seeds O's values as OPERATOR-trusted without their kind, so an own
id also clears an equal value of another kind at the integrity check (§7).

**1.4 Gap — entities created during the task.** An object created by a gated call in this session
(a file the agent created, an event it scheduled) should become own, with the record of that call
as its source — not because its id came back in a tool output. Not compiled (needs a kernel
record); listed in §7.

## 2. Tool model — what each tool does

`model/tools.yaml` gives the **effect** of every tool that changes something; every other tool is a
read. Reads are private unless listed `public` (third-party published content or workspace
structure).

| effect | class (§3.3) |
|---|---|
| read | BENIGN |
| write_own (inside the user's or the organisation's space) | REVERSIBLE |
| send, share, invite, pay, reserve, fetch (a URL leaves) | CONSEQUENTIAL |
| delete, credential | CATASTROPHIC |

**Argument roles**, from the schema (overridable per tool where a name misleads):
**destination** (recipient(s), cc, bcc, participants, email, user_email, user, channel, url; a
reservation's provider), **object** (`*_id`), **magnitude** (amount, dates/times), **content**
(free text: body, subject, title, description, content — `is_rich`), **other**.

## 3. Rules (fixed; the same for every deployment)

**3.1 Provenance.** Every non-content argument of a call with an effect must be *proven*: named by
the request (L1), own (L2 template from O), structured (L3) or confirmed (L4). Content is not
checked (§5).

**3.2 Own or named.** A destination or object of **any** call with an external effect (class above
BENIGN) is refused if it is neither own nor named by the request — before grants and before any
confirmation, so a confirmation cannot override it. Reversibility plays no part here.

**3.3 Consequence.** The class comes from the effect. Unattended ceiling: REVERSIBLE. Above it a
call needs a ground: CONSEQUENTIAL — any covering grant; CATASTROPHIC — L3/L4 only. Reversibility
lives only here — it sets the ceiling, which a degradation state may lower (specified, not wired:
the synchronous governor has no degradation engine).

**3.4 Confidentiality.** A private read arms the floor. While it is outstanding a destination
outside the audience (own ∪ the user's identifiers) needs a ground (named by the request, L1, L3,
L4); a write that carries content into an object seen by someone outside the audience is held; an
internal write is not.

**3.5 Grants are proof records.** A grant records *why* a tuple may run — source (L1 request, L2 own,
L3 structured, L4 confirmed), the tuple, a quota (`grant_quotas`, default 1) and, for a magnitude
argument, a limit ("a known payee, at most N"). L2 templates are compiled from O over the driving
arguments (revision 9). The magnitude limit is part of the model but **not compiled**: the kernel's
tuple templates take no limit (§7).

## 4. Compilation (model → kernel config, current format)

| kernel key | from |
|---|---|
| `untrusted_sources` | every read |
| `sensitive_sources` | every non-public read |
| `egress_sinks` / `integrity_sinks` | an effect with / without a destination argument |
| `access_control_sinks` | effect `credential` |
| `driving_args` | every non-content argument |
| `consequence_overrides`, `max_unattended_consequence` | effect → class; REVERSIBLE |
| `operator_sets` | own entities on destination/object arguments, by kind |
| `operator_sets_refuse_above: benign` | rule 3.2 |
| `floor_mode: audience`, `audience`, `destination_args`, `content_args`, `shared_stores` | rule 3.4 |

Diff against `config_rule` and the revision-13 config: `results/model_report.json`, §6.

## 5. Content role — a separate option, measured first

Rule 3.1 leaves content unchecked, and that is where the one attack that passes without a human
lives (slack injection 1: a direct message to Alice, an own member, with the attacker's link in
the body). Checking it means extracting URLs / addresses from free text by syntax — sub-field
parsing that the gate does not do (paper §5.6); admissible only as a projection over the rich
syntax with the premise "checked by fuzzing". Measured offline on AgentDojo's runs corpus
(`content_role_cost.py`; a token in a content argument that the request does not contain but an
earlier tool output does):

| | trajectories | flagged |
|---|---|---|
| benign (3 models) | 291 | 8 (slack 6, workspace 2) — 7 of them solved by the model |
| attacked, slack | 315 | 127 — injection 1 in 38 of its 63 |
| attacked, banking / travel / workspace | 432 / 420 / 720 | 29 / 4 / 24 |

Not compiled. Turning it on is a kernel change and a separate decision.

## 6. Validation (no live run)

Criterion: the compiled config reproduces what works and closes the known holes — O non-empty and
checked (§1.3), L2 bound to O (templates), `delete_file` CATASTROPHIC; Ajar (a)/(b)/(c) with CI,
replay 1887, routes 1–3, live v4/v5 and 288 benign replays. Results: §6.1 (filled after the runs).

## 7. Known gaps

- Entities created during the task (§1.4).
- Magnitude limits in L2 tuple templates (§3.5) — closed in M1 (§8.3).
- The content role (§5) — a second configuration in M1 (§8.4).
- O's values are seeded OPERATOR-trusted without their kind — closed in M1 (§8.2).
- Degradation states do not lower the ceiling in the synchronous governor (§3.3).
- Invariant 2 of the paper ("every egress destination is in the operator's allowlist") becomes
  "every destination or object of an effect is own, named by the request, or confirmed".

## 8. Revision M1 — fixed before code and runs

**8.1 Consequence class per call, κ(x) = effect × target × magnitude** (was: per tool).
- *Target*: a call is **own-targeted** when every value of its destination and object arguments
  is in that argument's own set (§1); otherwise **external**.
- *Magnitude bound* N (entity model): the largest amount the user has sent — own outgoing and
  scheduled transactions (banking: 1100).

| effect | own target | external target |
|---|---|---|
| read | BENIGN | BENIGN |
| write_own | REVERSIBLE | CONSEQUENTIAL |
| send, share, fetch | REVERSIBLE | CONSEQUENTIAL |
| invite (a new member), reserve | CONSEQUENTIAL | CONSEQUENTIAL |
| pay | CONSEQUENTIAL; CATASTROPHIC if amount > N | same |
| delete, credential | CATASTROPHIC | CATASTROPHIC |

A call whose κ is CATASTROPHIC takes L3/L4 only; a request (L1) or template (L2) grant that covers it
is not a ground, and the confirmation is asked instead.

**8.2 Own sets by slot** (kernel gap §7, closed). An own value is trusted only in a slot of its
own set — the (tool, argument) whose set contains it. It is no longer registered as a trusted
value everywhere; an own event id "13" does not clear a file id "13".

**8.3 Magnitude limit in L2 templates** (§3.5, closed). A magnitude argument with a limit is a
template component "≤ limit" (any provenance) instead of a request literal. Compiled: the banking
payment templates get `amount ≤ N`. One limit per sink (a per-payee limit is a refinement, not done).

**8.4 Content projection** (§5, as a second configuration `config_model_content`). From every
content argument of a call with an effect, tokens are extracted by syntax only — URL (with or
without scheme, `www.` or a dotted host with a TLD), e-mail, IBAN; no model, no meaning. Each token
must be own (in the audience, compared in canonical form by kind) or named by the request (by
canonical form); otherwise the call is refused, before grants and confirmation (as rule 3.2).
The extractor is covered by fuzz tests (tokens embedded in random text are found; text with no
`@`, no dotted host and no IBAN shape yields none). Paper §5.6 is extended with this projection
and its premise.

Runs: both configurations (`config_model`, `config_model_content`) on the free checks; the
pre-M1 `config_model` run is kept as M0.

**8.5 Unproven destination or object goes to a confirmation, not a refusal** (amends rule 3.2
for M1). A destination or object of a call with an effect that is neither own nor named by the
request makes the call need an L4 ground — a confirmation of that exact call (its digest) — instead
of being refused. A request (L1) or template (L2) grant that covers the call is not a ground for
it. The call is refused only when there is no human (no confirmer: configurations (a) and (b)) or
the human declines. The content projection (§8.4) is unchanged: a token that is neither own nor
named still refuses the call before any confirmation. The first M1 run (rule 3.2 refusing) was
stopped before it finished and is discarded.

**8.6 Driving arguments are the ones that choose the target** (amends §3.1 for M1, fixed before
the run). Driving = destination, object and magnitude, where magnitude is the amount only (dates
and times are role *other*). Dates, times, permissions, locations, flags and a new file's name are
not driving: they do not choose to whom, what or how much. Stated cost: an attacker who changes
only such a value (a date, a permission) is not caught by provenance.
