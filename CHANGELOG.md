# Changelog

## 0.3.3 — 2026-11-26

### Added

- **A made-up result in live work.** The audit of a recorded run
  (`audit.from_trace.evidence_from_trace`) used to count only a fault injected
  on purpose. A tool that really failed (an error status, HTTP 4xx/5xx) or a
  call the operator held (stopped, paused, budget spent), with an answer saying
  it worked, is now a `FABRICATED_TOOL_RESULT` case too — heuristic (confidence
  0.8, never the headline). A call the rules refused, a retry that worked and a
  tool broken on purpose are left alone.
- The calls one stop held make one case, not one per call, and its reason does
  not repeat that the call never ran.
- A live failure counts only when the answer speaks of the tool's subject — an
  effect verb counts (`Sent.` for `send_email`): a reconstructed claim lists
  every tool called, and a knowledge-base answer with no word of credit read as
  "said issue_credit succeeded".

## 0.3.2 — 2026-11-23

Needs **axor-wrap 0.4.0**: the `axor_wrap.connection` module `--plane` reads
below never shipped in a 0.3.x, so the floor now names a version that has it.
0.3.1 was tagged and never published — its release failed on exactly that
import.


- `--plane` uses the Control Plane and key saved by `axor-wrap connect` (axor-wrap
  0.3.1); nothing to export. The environment still wins.
- Setup health reads `AXOR_INGEST_KEY` like every other command (it read
  `AXOR_API_KEY` alone, so a machine connected the documented way posted with no
  key). `AXOR_API_KEY` still works.
- **A skill eval of one's own skill works.** A skill under evaluation that the
  repository already holds (`./.claude/skills/<name>`) crashed the run
  (`FileExistsError`) — and, had it not, the "none" arm would have run with the
  skill too. The copy now drops the evaluated skills; the arm alone installs them.

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
