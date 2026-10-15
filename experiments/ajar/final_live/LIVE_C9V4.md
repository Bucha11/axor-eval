# Live episodes changed by c9v4 (§9 references, 9.11, 9.13, 9.14a, 9.15/9.15a) — count only, NOT run

Replay of the 581 recorded live final-run episodes (o4-mini; A 290, B 291) through c814 (the live
configuration after the §8.14 re-run) and c9v4 (final_live/decisions_live.py; the agent's view =
references for hidden values; results/live_final_decisions_{c814,c9v4}_v.json;
results/live_c9v4_episodes.json). Cost = model calls of the episode x $0.00343 (the recorded mean:
$11.21 / 3267 calls of the live final run and the §8.14 re-run).

**Verdict changed** (a recorded call allowed in one and refused in the other), A only, 18 episodes,
102 model calls, about $0.35:

| config | pass | suite | user tasks |
|---|---|---|---|
| A | 1, 2, 3 | slack | 7, 9, 10, 12 (description grants) |
| A | 1, 2, 3 | workspace | 18 (named sender, 9.13), 20 (description: her email) |

**Confirmations changed** (B; the oracle confirms the same calls the A refusals hit), 19 episodes,
107 model calls, about $0.37 — B confirmations in all 291 episodes: 105 -> 80:

| config | pass | suite | user tasks |
|---|---|---|---|
| B | 1, 3 | slack | 7, 9, 10, 12 |
| B | 2 | slack | 1, 7, 9, 10, 12 |
| B | 1, 2, 3 | workspace | 18, 20 |

**The agent's view changed** (an output it read would carry references, §9): 323 episodes
(A 161, B 162; banking 66, slack 94, travel 16, workspace 147). A replay cannot say what the agent
does with a different input, so a valid live measurement of c9v4 re-runs every episode whose view or
decisions change: 335 episodes (A 167, B 168), 1589 model calls, about $5.45 — or the whole final run
(581 episodes, 2815 model calls, about $9.66) for a clean A/B pair.

Options, cheapest first: (1) the 37 verdict / confirmation episodes ($0.72) — measures the
description and named-sender gain but not the reference view, so it is not a valid estimate of c9v4;
(2) the 335 changed episodes (about $5.45); (3) the full run (about $9.66). Nothing is run until
approved.
