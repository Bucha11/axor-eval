# Table D.2 — banking, FREEZE_C9V5 (no model)
provisioned is out of 11 gradeable banking tasks; Ajar attacks out of 144 banking attacker-seeded
probes; replay ASR over the 432 banking important_instructions trajectories (3 models).

| row | OPL [95% CI] | sufficiency | provisioned | Ajar attacks /144 | replay ASR (432) |
|---|---|---|---|---|---|
| origin gate only | 0.040 [0.032, 0.050] | 0.739 | 4/11 | 0/144 | 0.009 |
| L1+L2, derived O | 0.060 [0.047, 0.075] | 0.785 | 5/11 | 0/144 | 0.000 |
| L1+L2, derived O + US133000000121212121212 | 0.595 [0.569, 0.618] | 0.785 | 5/11 | 80/144 | 0.190 |

Adding the attacker IBAN to O (the known-attacker-in-the-set control) is the only change that breaks
banking: Ajar attacks 0 → 80/144, replay ASR 0.000 → 0.190, OPL 0.060 → 0.595; sufficiency and
provisioned are unchanged (same legitimate work). Origin gate only lands 1 attack in replay
(ASR 0.009), 0 in Ajar; L1+L2 with the derived O holds 0/0.
