"""Context health for coding agents: does the team's agent setup still behave?

A coding agent's behaviour is set by the workspace more than by any one
session: CLAUDE.md / AGENTS.md, the installed skills, the model. Someone adds a
skill or edits CLAUDE.md, a model version changes — and every developer's agent
may now run what a README says to pipe into sh, or edit more than it was asked
to. Nobody notices until it happens.

This runs a fixed set of test tasks, in a throwaway sandbox, with the team's
setup copied in; compares how the agent behaved with the last check; and when
a kind of behaviour got worse, takes the setup apart — each skill, each
section of the instructions file, one at a time — to find the piece after
which it changed. Nothing in a developer's session is touched.

    python -m axor_eval.setup_health run spec.json [--baseline last.json] [--plane URL]
"""
from __future__ import annotations

from axor_eval.setup_health.report import compare, to_json, to_markdown
from axor_eval.setup_health.runner import run_check
from axor_eval.setup_health.setup import Fragment, discover
from axor_eval.setup_health.spec import HealthSpec, load_spec

__all__ = ["Fragment", "HealthSpec", "compare", "discover", "load_spec", "run_check",
           "to_json", "to_markdown"]
