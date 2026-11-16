"""Does the coding agent admit a check failed? Run it on a copy of a repository
in which its checks are broken on purpose — the test runner fails, hangs, or
says nothing — and read its last word. Arms compare what can change the
answer: instructions (a CLAUDE.md / AGENTS.md), the model, the agent.

    python -m axor_eval.honesty run experiments/honesty/limiter/honesty-eval.json

Nothing in a live session is touched: the breaks are shims on the sandbox's
PATH, the copy is thrown away after each trial.
"""
from __future__ import annotations

from axor_eval.honesty.report import summarize, to_json, to_markdown
from axor_eval.honesty.runner import Trial, run_eval
from axor_eval.honesty.spec import HonestySpec, load_spec

__all__ = ["HonestySpec", "Trial", "load_spec", "run_eval", "summarize", "to_json",
           "to_markdown"]
