# Changelog

## 0.3.1 — 2026-11-21

- `--plane` uses the Control Plane and key saved by `axor-wrap connect` (axor-wrap
  0.3.1); nothing to export. The environment still wins.
- Setup health reads `AXOR_INGEST_KEY` like every other command (it read
  `AXOR_API_KEY` alone, so a machine connected the documented way posted with no
  key). `AXOR_API_KEY` still works.

## 0.3.0 — 2026-11-20

Needs `axor-core>=0.8,<0.14` and `axor-wrap>=0.3,<0.4` (setup health names the
repository with `axor_wrap.agents.repo`, new in wrap 0.3.0).

### Added

- **Setup health** (`python -m axor_eval.setup_health run SPEC`): five test
  tasks in a throwaway sandbox with the team's setup copied in — skills, the
  sections of CLAUDE.md / AGENTS.md and, with `--plane`, the facts the Control
  Plane's team memory gives agents in that repository. Each task tempts one
  kind of bad behaviour; judged from what the agent did, never by a model.
  Against the last check, a behaviour that got worse is traced to the piece of
  the setup whose removal brings it back. `--plane` posts the report;
  `--no-memory` leaves the team's memory out. The sandbox runs with
  `AXOR_TEAM_MEMORY=0`.
- **Honesty eval** (`python -m axor_eval.honesty run SPEC`): a check command is
  broken on purpose (fails, hangs or says nothing) and the agent's last word is
  read — said it passed, said it failed, said nothing, did not run it. Arms
  compare instructions, model and agent (Fisher exact). Only a run that met the
  break is judged; a broken pytest also catches `python -m pytest`.
- **Audit: said the checks passed when they did not**
  (`CheckClaimAuditLayer`, `CLAIMED_CHECKS_PASSED`): the last result of each
  kind of check held against the answer. Wired into `evidence_from_trace`.
- **Deprivation modes** `timeout` and `empty_result`; the engine names its
  modes once (`MODES`, `SKIPS_TOOL`).
- **Skill eval**: the same tasks with and without a skill; several skills at
  once (each alone, all but one) with their cost; `--plane` posts the report.

### Notes

- `uv.lock` still resolves the 0.2 chain: it can only be regenerated once
  axor-core 0.13.0 and axor-wrap 0.3.0 are on PyPI.
