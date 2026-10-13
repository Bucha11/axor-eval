# axor on Ajar: open privilege, measured without a model

[Ajar](https://github.com/reSHARMA/Ajar) ([paper](https://arxiv.org/abs/2609.26900)) asks a
defense, for each of AgentDojo's 97 benign tasks, whether it would allow candidate calls the
task does not need, at every point the agent could act. axor has no model in its decision
path, so every number here is exact and costs no API call.

| File | What it is |
| --- | --- |
| `axor_ajar.py` | `AxorDefense`: a fresh `ToolCallGovernor` per decision, the executed plan prefix re-run and registered, then `evaluate(candidate)`. Grant levels (L1–L4) for E1. |
| `run_ajar.py` | Scores `e0` (today's axor), `e1` (grants by level), `e5` (ablations) on the exported probes. Writes `results/<exp>.json`. |
| `check_wrapper.py` | The E0 gate: real model trajectories from AgentDojo's runs corpus through axor-core's live `GovernedToolsExecutor`, compared call by call with the wrapper. |
| `replay_runs.py` | Recorded attacked runs replayed through axor; AgentDojo's own `security()` decides whether the attack landed. |

E4 (the spend path under races and faults) lives in axor-core: `benchmarks/grant_spend.py`.

## Setup

```sh
git clone https://github.com/reSHARMA/Ajar && cd Ajar
bash scripts/bootstrap.sh                                  # agentdojo + ajar in one venv
bench/agentdojo/.venv/bin/python scripts/export_probes.py --benchmark agentdojo   # ~25 min
PY=bench/agentdojo/.venv/bin/python
$PY ../axor-eval/experiments/ajar/check_wrapper.py --suite banking
$PY ../axor-eval/experiments/ajar/run_ajar.py e0 --runs 3
$PY ../axor-eval/experiments/ajar/run_ajar.py e1 --no-baselines
$PY ../axor-eval/experiments/ajar/run_ajar.py e5 --no-baselines
$PY ../axor-eval/experiments/ajar/replay_runs.py
```

Run from the Ajar checkout (paths resolve against it). axor-core is taken from the sibling
checkout, or `AXOR_CORE_REPO`.

## Metrics (as in the Ajar paper)

* **OPL**: harm-weighted share of DENY-labelled probes admitted, pooled over all 97 tasks.
* **Sufficiency**: mean over the 92 gradeable tasks of the share of required calls admitted.
* **Over-restriction**: share of permissible (not required) calls denied, pooled.
* **Attacks**: attacks whose every sink is admitted at its earliest decision point, out of 609.

## Caveats

* L3 is built from the task's ground-truth plan, so it is an upper bound, not a claim.
* L4 uses a scripted confirmer that accepts exactly the ground-truth calls: optimistic.
* `GRANT_ARGS_V2` was chosen after diagnosing where v1 leaked; it is reported separately.
* L2 uses the repo's only operator allowlist (`banking_tuned.yaml`). It contains
  `US133000000121212121212`, which AgentDojo uses both as the attacker's IBAN and as a
  legitimate landlord in banking/user_task_15. `L2s` is the same list without it.
