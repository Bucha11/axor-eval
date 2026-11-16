"""Does a skill help? An A/B eval for coding-agent skills.

A skill (a folder with ``SKILL.md``, often scripts beside it) is installed so a
coding agent can do some kind of task better. Whether it does is measurable: the
same tasks, run by the same agent from the same starting repository, with the
skill installed and without it — each trial judged by a check command (the
task's tests: exit 0 = solved), never by what the agent says it did.

    python -m axor_eval.skills run experiments/skills/example/skill-eval.json

Per task and arm: solved k/n, tokens, turns, wall time, and whether the agent
opened the skill at all — a skill the agent never read cannot be credited with
the result, and a "with" arm that never opens it is reported as such. The lift
(solved rate with − without) comes with a two-sided Fisher exact p, so a
difference of one trial in three is not mistaken for an effect.
"""
from __future__ import annotations

from axor_eval.skills.report import ArmSummary, TaskSummary, summarize, to_markdown
from axor_eval.skills.runner import TrialResult, run_eval, run_trial
from axor_eval.skills.spec import EvalSpec, Task, load_spec

__all__ = [
    "ArmSummary", "EvalSpec", "Task", "TaskSummary", "TrialResult",
    "load_spec", "run_eval", "run_trial", "summarize", "to_markdown",
]
