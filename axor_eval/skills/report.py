"""From trials to an answer: did the skill help, on which tasks, at what cost.

The verdict is about the check (solved or not), never the agent's own words.
The lift is the solved rate with the skill minus without, and it carries a
two-sided Fisher exact p — with three trials an arm, 3/3 against 1/3 is
p = 0.4, which is "maybe", not "helps". A "with" arm whose agent never opened
the skill is called out: whatever happened there, the skill did not cause it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import comb
from statistics import mean

from axor_eval.skills.runner import TrialResult

SIGNIFICANT = 0.05


@dataclass
class ArmSummary:
    trials: int
    solved: int
    rate: float
    mean_input_tokens: float
    mean_output_tokens: float
    mean_turns: float
    mean_duration_s: float
    errors: int
    skill_opened: int | None      # trials in which the agent opened it (with arm)


@dataclass
class TaskSummary:
    task: str
    without: ArmSummary
    with_skill: ArmSummary
    lift: float
    p_value: float
    verdict: str

    def as_dict(self) -> dict:
        return asdict(self)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2×2 table [[a, b], [c, d]]
    (solved / not, with / without) — exact, no normal approximation, which
    a handful of trials an arm would make meaningless."""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2

    def p(x: int) -> float:
        return comb(n1, x) * comb(n2, k - x) / comb(n, k)

    observed = p(a)
    lo, hi = max(0, k - n2), min(k, n1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= observed * (1 + 1e-9)))


def _arm(rows: list[TrialResult], with_arm: bool) -> ArmSummary:
    solved = sum(r.solved for r in rows)
    known = [r.skill_opened for r in rows if r.skill_opened is not None]
    return ArmSummary(
        trials=len(rows), solved=solved, rate=round(solved / len(rows), 3) if rows else 0.0,
        mean_input_tokens=round(mean(r.input_tokens for r in rows), 1) if rows else 0.0,
        mean_output_tokens=round(mean(r.output_tokens for r in rows), 1) if rows else 0.0,
        mean_turns=round(mean(r.turns for r in rows), 1) if rows else 0.0,
        mean_duration_s=round(mean(r.duration_s for r in rows), 1) if rows else 0.0,
        errors=sum(bool(r.error) for r in rows),
        skill_opened=sum(bool(x) for x in known) if with_arm and known else None,
    )


def _verdict(w: ArmSummary, wo: ArmSummary, lift: float, p: float) -> str:
    if w.skill_opened == 0:
        return "never opened — the agent did not read the skill"
    if lift > 0 and p < SIGNIFICANT:
        return "helps"
    if lift < 0 and p < SIGNIFICANT:
        return "hurts"
    if lift == 0 and w.rate in (0.0, 1.0):
        both = "both always solve it" if w.rate == 1.0 else "neither solves it"
        return f"no difference — {both}"
    if w.trials < 5:
        return "not enough trials to tell"
    return "no clear difference"


def summarize(results: list[TrialResult]) -> list[TaskSummary]:
    out: list[TaskSummary] = []
    for task in dict.fromkeys(r.task for r in results):
        w_rows = [r for r in results if r.task == task and r.arm == "with"]
        wo_rows = [r for r in results if r.task == task and r.arm == "without"]
        w, wo = _arm(w_rows, True), _arm(wo_rows, False)
        lift = round(w.rate - wo.rate, 3)
        p = round(fisher_exact(w.solved, w.trials - w.solved,
                               wo.solved, wo.trials - wo.solved), 4)
        out.append(TaskSummary(task, wo, w, lift, p, _verdict(w, wo, lift, p)))
    return out


def overall(summaries: list[TaskSummary]) -> dict:
    """Pooled over tasks: every trial of every task in one 2×2."""
    ws = sum(s.with_skill.solved for s in summaries)
    wn = sum(s.with_skill.trials for s in summaries)
    os_ = sum(s.without.solved for s in summaries)
    on = sum(s.without.trials for s in summaries)
    p = fisher_exact(ws, wn - ws, os_, on - os_) if wn and on else 1.0
    return {"with": f"{ws}/{wn}", "without": f"{os_}/{on}",
            "lift": round(ws / wn - os_ / on, 3) if wn and on else 0.0, "p_value": round(p, 4)}


def _tok(a: ArmSummary) -> str:
    return f"{a.mean_input_tokens + a.mean_output_tokens:,.0f}"


def to_markdown(skill: str, agent: str, summaries: list[TaskSummary]) -> str:
    rows = [f"# Skill eval: {skill} ({agent})", "",
            "| task | without | with | lift | p | tokens without → with | turns | opened "
            "| verdict |",
            "|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        w = s.with_skill
        opened = "—" if w.skill_opened is None else f"{w.skill_opened}/{w.trials}"
        rows.append(
            f"| {s.task} | {s.without.solved}/{s.without.trials} | {w.solved}/{w.trials} "
            f"| {s.lift:+.0%} | {s.p_value:.3g} | {_tok(s.without)} → {_tok(w)} "
            f"| {s.without.mean_turns:g} → {w.mean_turns:g} | {opened} | {s.verdict} |")
    o = overall(summaries)
    rows += ["", f"Overall: {o['with']} solved with the skill, {o['without']} without "
                 f"(lift {o['lift']:+.0%}, Fisher exact p = {o['p_value']:.3g}).",
             "", "Solved = the task's check command exited 0 after the agent finished. "
                 "Opened = trials in which the agent called the skill or read a file under it."]
    return "\n".join(rows) + "\n"
