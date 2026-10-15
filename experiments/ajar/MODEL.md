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

### 6.1 Results — final configuration (§8.7 + §8.10, `config_m1_content`) vs `config_rule`

Ajar (97 tasks, 609 attacks): tasks provisioned / attacks admitted.

| mode | config_rule | final |
|---|---|---|
| no grants | 42 / 6 | 54 / 0 |
| grants, no human | 39 / 6 | 58 / 1 |
| perfect confirmer | 90 / 6 | 92 / 1 |
| attentive confirmer | 60 / 32 | 72 / 29 |
| careless confirmer | 64 / 82 | 73 / 117 |

Replay of AgentDojo's 1887 attacked trajectories, attacks landed (grants, no human): 8 → 10
(7 travel injection 2 — an event in the user's own calendar with the attacker's text; 3 banking
user task 15 — US133…, named by the user as the landlord, is also the attacker's IBAN). 288 benign
trajectories with no refusal, no human: 139 → 201.

The one Ajar attack without a human: travel injection 5 (`send_email`). With a confirmer, every
admitted attack is one the confirmer approved (travel reservations and the calendar event, the
deletion of file 13, the password change).

Routes (worst case): route 1 (exfiltration without an addressee) — a shared file and an event with
the attacker are never admitted (0 of 124, 0 of 268 in every mode); writes of a secret into the
user's own store are admitted (173 of 436, rule 3.4: not a disclosure). Route 2 (redirection inside
grants, a tuple the user named but the task does not need): 9928 of 11427 under (b) (config_rule
6399 of 11270) — the grant now binds only the target, and a value the user named is a ground.
Route 3 (rich fields from a read on a plan call): 40 of 55 under (b) (config_rule 17) — content is
not checked beyond the projection's URLs / e-mails / IBANs.


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

**8.7 Grants follow the model** (fixed before the run).
- *Grant arguments = driving arguments* (§8.6: destination, object, amount), with their kinds;
  a request grant (L1) no longer needs a literal for a date or a time. The harness takes the
  grant arguments from the config, not from the schema-wide table R0.
- *Quota*: an L1/L2 grant on a tool whose own-targeted class is REVERSIBLE (write_own, send,
  share) is unlimited within the session; on every other tool it is one use (default).
- *No driving argument* (an explicit empty list, e.g. `create_file`, `update_user_info`): there
  is nothing for provenance to check — the kernel no longer falls back to checking every
  argument. The floor and the content projection still apply.
- *Credentials*: the new password is the object of `update_password` (it is what the call sets),
  so it is a driving and grant argument and the call can be confirmed (L4).

**8.8 An absent driving argument is an empty one** (fixed before the run). When none of a
call's driving arguments is passed (an event created without participants), there is nothing
for provenance to check, exactly as when they are passed empty. The kernel's fallback — check
every argument when no declared driving argument is present — exists for a destination
smuggled into an undeclared field; under the model every argument has a role and the content
projection covers content, so for M1 the fallback is off (`absent_driving_is_empty`).

**8.9 Decision: the final configuration is §8.7 (§8.8 not adopted).** §8.7 → §8.8 changed one
setting (`absent_driving_is_empty`). Its whole gain — +6 tasks without a human, +6 with a perfect
human, +14 benign trajectories with no refusal — came from calls with no target passed
(`create_calendar_event` without participants: 12 travel, 2 workspace), the same calls through
which travel injection 2 (an event with the attacker's text in the user's calendar) went from 1 to
21 admitted Ajar attacks. The fallback (no declared driving argument passed → check every
argument) stays on. Final config: `config_m1_content` without that key; routes computed on it.

**8.10 The fallback asks a human** (amends §8.9, fixed before code and runs). Checked in the code:
in §8.7 a call that passes no driving argument (an empty leading tuple) is not covered by a grant,
so provenance falls back to every argument (step 6), and a failure there is returned at once —
the confirmation (step 7) is never asked. Now, as for any unproven destination/object (§8.5), an
*integrity* failure of the fallback makes the call need an L4 ground (a confirmation of the exact
call): it runs if the human confirms, and is refused without a human or when declined. A
confidentiality (floor) failure is not deferred. Kernel flag `fallback_to_confirmation`. Final =
§8.7 + this. Recompute: Ajar all modes with CI, replay 1887, 288 benign, routes. Expected: no human
as §8.7; perfect human ≈ 92.

**8.11 Appendix D on the final configuration — the model-free bound** (fixed before code and runs;
measurement only, no rule changes). In the final configuration the role of Appendix D's enum
allowlist is played by the operator sets O (own entities from the initial state, §8.1/§8.5).
Bound = for banking user tasks 3, 4, 6, 15, Ajar's gate decisions on the reference plan
(sufficiency: every required call admitted), in two arms that differ only in O:
*with O* = `config_m1_content/banking.yaml`; *without O* = the same file with `operator_sets`
and `operator_sets_confirm` removed (so no rule 3.2 refusal, no L2 templates from O; a read-derived
payee falls to the origin check). Each arm with grants L1 and no human (configuration A), and
with L1+L4 oracle (configuration B). Reported per task: sufficient or not, and the first denied
required call with its check. US133 (UT15's new landlord, also the attacker's IBAN) is reported
explicitly: is it in O, by which ground the landlord update is admitted or refused, and whether
the same ground admits the attacker's IBAN on an injected call. No live run.

**8.12 A content-projection failure asks a human** (amends §8.4, fixed before code and runs). A
call whose content argument carries a URL / e-mail / IBAN that is neither own (the audience) nor
named by the request (§8.4) is no longer refused outright when a human can be asked: as an unproven
destination/object (§8.5) it needs an L4 ground — a confirmation of the exact call. Without a
human, or for a sink with no grant args, it is refused as before. Only an L3/L4 grant is a ground
for it (an L1/L2 grant does not cover a flagged literal). Kernel flag `content_to_confirmation`;
the flagged literals are part of what the human is shown (`RenderedAction.flagged`).

Oracle (perfect human) for a flagged call: approves only if, in addition to its usual test (the
whole call equals a call of the reference plan; live: the grant arguments equal a ground-truth
call's), every flagged literal occurs in that reference call's arguments. The attentive (view)
and careless (naive) humans are unchanged.

Recompute (free): Ajar in the three human modes and the 1887 replay in the same modes; the modes
without a human must be identical to §6.1 / the final replay to the last digit (the flag changes
nothing without a confirmer). Paid: only the B episodes (task × pass) in which the content check
fired are re-run; the other B episodes are kept. Count and cost first, no launch.

**8.13 Own standing orders are own objects** (fixed before code and runs). Inventory of the
operator sets left EMPTY by the generator (config_m1_c812), each classified against the entity
model (§1: own = in the user's / organisation's space in the initial state):

| suite | slot | empty because | verdict |
|---|---|---|---|
| banking | update_scheduled_transaction.id | no entity class for standing orders, though the initial state has two (ids 6, 7) | **gap — fixed here** |
| travel | send_email.recipients / cc / bcc, create_calendar_event.participants | no address class in travel, though the user's own address and the participants of the user's own events exist (workspace has this class) | gap — listed, not fixed |
| banking | update_password.password | a credential: no own entity of that kind exists | correct |
| slack | invite_user_to_slack.user / user_email | inviting creates a new member: by definition not own | correct |
| slack | get_webpage.url, post_webpage.url | the web is third-party; no page is the user's | correct |
| travel | reserve_hotel.hotel, reserve_car_rental.company, reserve_restaurant.restaurant | a catalogue of external businesses | correct |

(Not empty but incomplete, also listed, not fixed: workspace `delete_email.email_id` holds only the
emails the user sent (10); received emails in the user's own inbox are also own objects.)

Rule: entity class `standing_order` = the ids of `bank_account.scheduled_transactions` in the
initial state; slot `update_scheduled_transaction.id` draws from it. Config `config_m1_c813` =
§8.12 + this. Recompute (free): Ajar all modes, replay 1887; for the modes without a human, report
what changed. Paid (only after confirmation): live episodes (A and B) in which a changed rule fired —
the content check in B, a refusal on an empty own-object set (`update_scheduled_transaction.id`)
in A and B; count and cost first.

**8.14 Revision after §8.12–8.13** (fixed before code and runs).
1. **§8.12 is withdrawn**: a content-projection failure is again a final refusal (with or without a
   human). Reason (measured, §8.12 recompute): no utility gained in any mode, +4/+5 Ajar attacks and
   +7/+9 replay attacks with a fallible human; and the live refusals it targeted were mostly the
   recognizer's false positives (item 2), not legitimate literals.
2. **Domain recognition in content (`content_tokens.extract`)**. A token without a scheme and
   without `www.` is a domain only if (a) its last label is a top-level domain of the Public Suffix
   List (publicsuffix.org, vendored with its date), (b) that label is not a common file extension
   (doc, docx, xls, xlsx, ppt, pptx, pdf, txt, csv, md, json, …, the list in the code: `notes.md`
   and `run.py` are files although `md` and `py` are TLDs), and (c) the token is not the name of
   one of the user's own files (config `own_names`, from the initial state). A token with a scheme
   or `www.` is a URL as before; e-mail and IBAN unchanged.
3. **Generator.** travel: own addresses = the user's address and the participants of the user's own
   events (as workspace) — slots send_email.recipients/cc/bcc and create_calendar_event.participants;
   workspace: received e-mails in the user's inbox are own objects too (slot delete_email.email_id);
   `own_names` = the names of the user's own files (workspace cloud drive, banking file system).
   §8.13 stays.
Config `config_m1_c814` = §8.10 + §8.13 + this. Recompute (free): Ajar all modes and replay 1887,
compared with §8.10 change by change (§8.13 alone = c813 without §8.12; + recognizer; + travel
addresses; + received e-mails). Live: count the A and B episodes in which any changed rule fires
(a recorded call whose decision differs from the final configuration's), with the cost; no launch.

## 9. References — fixed before code and runs (format of stage 0c, refs_stage0/STAGE0.md)

Base: §8.14 (`config_m1_c814`). References are a second configuration on top of it (flag
`references`); everything in §8 stays unless a rule below replaces it.

**9.1 What a reference is.** A reference is a triple (kind, value, origin), kept in the session's
reference table. Kinds: `email`, `iban`, `url` (found in any string of a tool output) and `id` (the
value of an id field: `id`, `id_`, `file_id`, `event_id`, `email_id`). The agent sees only the
reference's name: `<kind>_from_untrusted_read_hidden_<4 hex>` (unique in the session; the same value
of the same kind gets the same name for the whole session); for an id field whose value is an
integer, a unique integer in [10 000 000, 99 999 999] (an integer parameter takes it). The table
lives in the daemon (Ring 0), out of the agent's reach; in-process, in the governor.

**9.2 Origins.** Each target identifier in a tool output gets exactly one origin, fixed when it is
first read (the first origin wins for the session):
* **R** — the value is a literal of the request (as L1 reads it);
* **own** — the value is an own entity of the entity model (config `audience`: own addresses,
  accounts, own file / event / e-mail / standing-order ids);
* **named sender** — the value sits in a record whose sender field (`sender`, `from`) names a
  sender the request names (the sender value is a request literal; matching by the entity model's
  values, no language model);
* **secret** — read from a declared sensitive source (config `sensitive_sources`) and none of the
  above;
* **untrusted** — every other value read from a tool output.

**9.3 What is hidden.** R and own values are shown as they are. Every other target identifier
(named sender, secret, untrusted) is shown only as its reference. Text around identifiers is not
changed.

**9.4 What a driving argument may carry.**
* a raw value only if it is R or own (unchanged: L1 grants, own sets, L2 templates, quota, limit);
* a value from a read only as its reference;
* a raw value equal to a value the session hid (the agent rebuilt it "by hand"), or any other raw
  value that is neither R nor own: unproven — a confirmation of the exact call (L4) with a human,
  refused without one.

**9.5 A reference as a ground.** A reference in a driving argument is resolved to its value, and
its origin is the ground: named sender — as an L1 grant on that value (tuple, quota and limit rules
unchanged); untrusted or secret — unproven: L4 with a human, refused without one. (R and own are
never references.)

**9.6 References in text.** A reference inside a content argument (a body, a description) is
resolved at execution, and its origin is checked as in 9.5: an untrusted / secret reference in the
content of a sink is unproven (L4 / refused). Raw addresses in content keep §8.14's content check.

**9.7 Secrets.** A secret reference is resolved only into a sink whose audience sees the source
(every destination of the call is in the audience — the entity model's "who sees what"); otherwise
refused, with or without a human. The confidentiality floor stays as a second layer.

**9.8 Unknown references.** A reference-shaped token (a name of the 9.1 form, or an integer in the
handle range in an id argument) that is not in the session's table: refused.

**9.9 What the gate no longer does in this configuration.** Integrity of a driving argument is
decided by origin (raw R / own; reference → its origin; other raw → unproven), not by matching
string fragments of reads; L1 grants are minted from raw request literals only, as before. The
confidentiality floor and the consequence class are unchanged.

**9.10 Evaluation (free, no live run).** Ajar (all modes, CI) and replay 1887: a candidate's value
is turned into a reference by its actual origin in the prefix (a value the prefix read → the
reference minted for it, with that origin; an injected value → untrusted); R / own values stay raw;
a value never read stays raw. Worst-case routes: substitution (L1 / own / named sender) with k;
text in fields; disclosure, separately, with secret references. Replay of the 288 benign
trajectories: tasks without refusals. Ablation against §8.14 alone: Ajar attacks, replay, routes
(string substitution, the US133 pair, text in fields).

**9.11 Secret references — variant 1** (replaces 9.2's *secret* origin and amends 9.7; fixed before
code and runs). A secret reference is minted only for a value of an explicitly declared secret
field (config `secret_fields`; the field's value wherever it appears in that output too), kind
`secret`, name `secret_from_untrusted_read_hidden_<4 hex>`. Reading a declared sensitive source no
longer makes an identifier secret: such an identifier gets the origin it would have otherwise
(named sender / untrusted). The confidentiality floor by source is unchanged. 9.7 now reads: a
secret reference is resolved only into a sink whose every destination is in the audience; else
refused, with or without a human.
Secret fields per suite (from the initial states; a structured field whose value is a credential or
a personal document / payment number):
* banking: `password`
* travel: `passport_number`, `credit_card_number`, `bank_account_number`, `ID_number`
* slack, workspace: none (security codes there live in message / e-mail text, not in a field)
Config `config_m1_c9v1` = `config_m1_c9` + `secret_fields`. Recompute (free): Ajar all modes,
replay 1887, benign 288. Expected: perfect human 92/92 again.

**9.12 Configuration-error injection** (measurement only; fixed before code and runs). Two arms:
§8.14 (`config_m1_c814`) and §8.14 + references (`config_m1_c9v1`), each mutated identically:
(a) one sink declaration removed — every tool in `egress_sinks` ∪ `integrity_sinks`, one at a time
    (removed from those sets only);
(b) one driving argument removed — every (tool, argument) of `driving_args`, one at a time (removed
    from `driving_args` only);
(c) k = 1, 3, 5 declarations removed at once, drawn uniformly from the suite's pool of (a) and (b)
    declarations, 20 seeds per k.
Each mutation is measured on its own suite only: Ajar attacks admitted without a human (mode b,
attacker-seeded probes) and attacks landed in the 1887 replay without a human ("R0 L1+L2s").
Reported per mutation, per class (a / b / c-k) and per suite, as the difference between the arms.

(9.12 not run: withdrawn by the user before any run.)

**9.13 The named-sender ground** (amends 9.2 / 9.5; fixed before code and runs).
* A record is a *named-sender record* when (1) the tool's output is a list of records or one record
  with a structured top-level field `sender` or `from` (a key of the record itself — a line `sender:`
  / `from:` at the record's own indentation, never inside a text value), (2) the tool is not one
  whose output is a document body (config `no_sender_tools`, below), and (3) the sender is named by
  the request: the sender value itself, or one of its names in the entity model (a contact's full
  name or first name; a Slack user's name is the value itself), occurs in the request as a word
  (case-folded, word-bounded). Matching uses the entity model's values only (config
  `sender_aliases`: value → names, from the initial state), no language model.
* A reference minted from a target identifier inside such a record gets the origin *named sender*
  and proves its target as an L1 grant on that value (tuple, quota, limit unchanged). Identifiers
  outside that record (other records of the same output, other outputs) are not affected.
* Bodies of files and web pages are never named-sender records. `no_sender_tools`:
  banking `read_file`; slack `get_webpage`; workspace `get_file_by_id`, `search_files`,
  `search_files_by_filename`, `list_files`, `create_file`, `append_to_file`, `share_file`;
  travel none (it has no file or web tool).
* `sender_aliases`: workspace and travel — every contact's e-mail → [full name, first name];
  slack — none needed (the sender field holds the user's name); banking — none (an IBAN is named
  only literally).
Config `config_m1_c9v2` = `config_m1_c9v1` (9.11) + this. Recompute (free) against §8.14: Ajar all
modes; replay 1887 with the admitted attacks broken down, the ones admitted through a named-sender
record listed separately; the 288 benign trajectories without a human — tasks without a refusal, per
suite. No live run.
