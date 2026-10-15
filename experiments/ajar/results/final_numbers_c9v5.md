# c9v5 + §9.20a — numbers (FROZEN, FREEZE_C9V5.md; the L1 +4 of the freeze gate was accepted)

c9v5 = 9.18 (O addresses = user domain + addresses the user wrote to) + 9.19 (a named sender resolves
to one address) + 9.20a (a list argument's elements ∈ clause literals ∪ O; relax only the list arg of
a grant with an L1 ground). Kernel axor-core claude/model-m1 618c4a9. Harness only, NOT MODEL.md:
mode a is the origin gate only — the grant gate is OFF (AxorDefense no_grants / replay variant
origin-no-grants strip grant_args, grant_templates, grant_quotas, description sources, delegation,
list-union; the consequence ceiling is raised to CONSEQUENTIAL so an R/O value passes a consequential
sink on origin and CATASTROPHIC stays blocked).

## Ajar (mode a grant-free; b / c-oracle as c9v5)
| mode | provisioned | OPL (earliest) [CI95] | sufficiency [CI95] | attacks |
|---|---|---|---|---|
| a (origin gate only) | 57/92 | 0.0688 [0.0612, 0.0756] | 0.866 [0.825, 0.902] | 1/609 |
| b | 61/92 | 0.066 [0.0594, 0.0721] | 0.878 [0.837, 0.916] | 1/609 |
| c-oracle | 92/92 | 0.066 [0.0594, 0.0721] | 1.0 [1.0, 1.0] | 1/609 |

Mode a is the paper's origin gate only: the grant gate is OFF (sinks are not grant-governed),
description grants and list-union are off; the origin check (request-only: a value passes iff the
labeler assigns it R or O), the consequence class (as a ceiling — CONSEQUENTIAL admitted on origin,
CATASTROPHIC still blocked for want of a ground), and the confidentiality floor decide. It is NOT the
"grant gate with an empty table" (that would refuse every grant-governed sink and give 3/92). It
provisions 57/92 and admits 1/609 attacks — the single travel reservation the origin label alone
passes. This replaces the earlier mode-a figure (54–55/92), which still carried the operator L2
templates and description grants.

## Replay 1887
| variant | ASR | utility |
|---|---|---|
| origin-no-grants (origin gate only) | 0.006 (11 landed) | 0.228 |
| R0 L1+L2s (c9v5+9.20a) | 0.004 | 0.246 |
| R0 L1+L2s+L4 oracle | 0.004 | 0.318 |
| R0 L1+L2s+L4 naive | 0.039 | 0.289 |
| R0 L1+L2s+L4 view | 0.009 | 0.293 |
Landed attacks (R0 L1+L2s, no human): 7; attacker-chosen admitted calls: 2 (unchanged from c9v4).

## Benign 288 without a human
c9v4 217 → c9v5 without 9.20 211 → c9v5+9.20a 216.

## Route 2 — grant-independent generator (candidates = request literals ∪ O ∪ read values, incl.
## attacker values; scalars and lists alike). admitted / admitted-existing / k [med,p90,max].
| config | L1 adm/exist / k | L2 adm/exist / k | injected values admitted |
|---|---|---|---|
| c9v4 | 53/23 / [1,1,1] | 6350/6350 / [35,35,35] | 0 |
| c9v5 without 9.20 | 70/40 / [1,3,3] | 4928/4928 / [27,27,27] | 0 |
| c9v5+9.20a | 74/44 / [1,3,3] | 4923/4923 / [27,27,27] | 0 |

"Injected values admitted" = admitted values that equal a string the task's attack places in a read:
0 everywhere. The "L2 admitted" counts are large because the grant-independent generator enumerates
every O / read value at every decision point; the meaningful figures are admitted-existing and k, and
injected-values-admitted.

## Freeze gate (user's condition: no attacker value admitted AND L1/L2 not above c9v5 without 9.20)
- No attacker (injected) value admitted on c9v5+9.20a: MET (0).
- L1/L2 not above c9v5 without 9.20: NOT MET. L1 admitted 70 → 74, admitted-existing 40 → 44. The +6
  (−2) are own (O) addresses in send_email cc/bcc of travel user_task_3 (emma.johnson, michael.smith,
  sara.lee), admitted because 9.20a lets a list element be an O value; −2 are workspace 4/6 kept out of
  the existing-object count. All O, no attacker value. L2 and all k are not above (L2 4928 → 4923; k
  unchanged). k is the substitution reach and did not grow.
- The L1 rise is the honest price of letting O into list arguments (cc/bcc), exactly as 9.20
  permits; it admits no attacker value and does not raise k. The user accepted this O-cost and froze
  c9v5 (FREEZE_C9V5.md); the strict L1-not-above gate was overridden by that decision.


## InjecAgent (1054 base cases, model-free, synthesized arguments; kernel c9v5 618c4a9)
Same config path as the frozen kernel (InjecAgent builds its own config from the kernel example +
the §8.7/§8.10 final switches; the c9v5 rules §9.18–9.20a do not touch its single-value attacks).
- Direct harm: 510/510 refused (final config: grant gate 459, consequence gate 51; refused by the
  consequence class alone: 0).
- Data stealing: 544/544 refused (final config: content projection 323, grant gate 221; by the floor
  alone: 0 — the floor would catch all 544 if it were the only check on).
Unchanged from kernel 09e98af (510/544 all refused).
