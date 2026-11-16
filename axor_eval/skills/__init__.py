"""Which skills help, and what they cost? An ablation eval for coding-agent skills.

Skills (folders with ``SKILL.md``, often scripts beside them) are installed so a
coding agent does some kind of task better. Whether each one does is
measurable: the same tasks, run by the same agent from the same starting
repository, with no skill, with all of them, with each one alone and with all
but one — each trial judged by a check command (the task's tests: exit 0 =
solved), never by what the agent says it did.

    python -m axor_eval.skills run experiments/skills/changelog/skill-eval.json

Per skill: what it does alone, what it adds on top of the others, whether the
agent opened it at all, and what it costs in tokens — per run, per SOLVED task,
and just for being installed. Solved-rate differences carry a two-sided Fisher
exact p, token differences a 95% bootstrap interval.
"""
from __future__ import annotations

from axor_eval.skills.report import (
    ArmSummary,
    Compare,
    SkillSummary,
    TaskSummary,
    per_skill,
    per_task,
    summarize,
    to_json,
    to_markdown,
)
from axor_eval.skills.runner import TrialResult, run_eval, run_trial
from axor_eval.skills.spec import Arm, EvalSpec, Skill, Task, load_spec

__all__ = [
    "Arm", "ArmSummary", "Compare", "EvalSpec", "Skill", "SkillSummary", "Task",
    "TaskSummary", "TrialResult", "load_spec", "per_skill", "per_task", "run_eval",
    "run_trial", "summarize", "to_json", "to_markdown",
]
