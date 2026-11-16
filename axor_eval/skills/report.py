"""From trials to an answer: which skill helps, on which tasks, at what cost.

Two questions per skill, both against evidence from the check (solved or not),
never the agent's own words:

- **alone** — ``only:<s>`` against ``none``: does it help by itself?
- **on top of the others** — ``all`` against ``without:<s>``: does it still
  add something when the rest are installed, or do they already cover it?

And what it costs: tokens per run (fresh input, cache reads, output — kept
apart, because they are priced apart), the agent's reported cost, tokens per
SOLVED task (a cheaper arm that solves less is not cheaper), and the tokens a
skill costs just by being installed (its frontmatter rides in every context).

Every solved-rate difference carries a two-sided Fisher exact p (3/3 against
0/3 is p = 0.1: "not enough trials", not an effect); every token difference a
95% bootstrap interval (fixed seed, reproducible). A skill the agent never
opened gets no credit for what happened while it was installed.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from math import comb
from statistics import mean, median

from axor_eval.skills.runner import TrialResult
from axor_eval.skills.spec import BASELINE, EvalSpec

SIGNIFICANT = 0.05
_BOOT = 2000
CHARS_PER_TOKEN = 4   # a rough English-text average, for the always-carried estimate


@dataclass
class ArmSummary:
    arm: str
    skills: list[str]
    trials: int
    solved: int
    rate: float
    mean_tokens: float
    median_tokens: float
    mean_input_tokens: float
    mean_cache_read_tokens: float
    mean_output_tokens: float
    mean_cost_usd: float | None
    tokens_per_solved: float | None
    cost_per_solved_usd: float | None
    mean_turns: float
    mean_duration_s: float
    errors: int
    opened: dict[str, int] | None    # per skill: trials in which the agent opened it


@dataclass
class Compare:
    """``arm`` against ``base``: positive lift = solves more; positive token
    delta = spends more."""
    arm: str
    base: str
    lift: float
    p_value: float
    token_delta: float
    token_delta_ci: tuple[float, float] | None
    token_change: float | None       # relative to the base's mean
    cost_delta_usd: float | None


@dataclass
class TaskSummary:
    task: str
    arms: list[ArmSummary]
    vs_none: list[Compare]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillSummary:
    skill: str
    carried_tokens: int              # ~tokens in every context while installed
    body_tokens: int                 # ~tokens when the agent opens it
    alone: Compare | None
    on_top: Compare | None
    opened: str                      # "k/n" over trials it was installed in, or "unknown"
    verdict: str

    def as_dict(self) -> dict:
        return asdict(self)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2×2 table [[a, b], [c, d]]
    (solved / not, arm / base) — exact, no normal approximation, which a
    handful of trials an arm would make meaningless."""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2
    if n == 0:
        return 1.0

    def p(x: int) -> float:
        return comb(n1, x) * comb(n2, k - x) / comb(n, k)

    observed = p(a)
    lo, hi = max(0, k - n2), min(k, n1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= observed * (1 + 1e-9)))


def bootstrap_diff(xs: list[float], ys: list[float], *,
                   seed: int = 0) -> tuple[float, float] | None:
    """95% interval of mean(xs) − mean(ys), resampling each side."""
    if len(xs) < 2 or len(ys) < 2:
        return None
    rng = random.Random(seed)
    diffs = sorted(mean(rng.choices(xs, k=len(xs))) - mean(rng.choices(ys, k=len(ys)))
                   for _ in range(_BOOT))
    return round(diffs[int(0.025 * _BOOT)], 1), round(diffs[int(0.975 * _BOOT) - 1], 1)


def _summary(label: str, rows: list[TrialResult]) -> ArmSummary:
    solved = sum(r.solved for r in rows)
    costs = [r.cost_usd for r in rows if r.cost_usd is not None]
    known = [r.opened for r in rows if r.opened is not None]
    skills = rows[0].skills if rows else []
    total = [r.total_tokens for r in rows]
    return ArmSummary(
        arm=label, skills=list(skills), trials=len(rows), solved=solved,
        rate=round(solved / len(rows), 3) if rows else 0.0,
        mean_tokens=round(mean(total), 1) if rows else 0.0,
        median_tokens=float(median(total)) if rows else 0.0,
        mean_input_tokens=round(mean(r.input_tokens for r in rows), 1) if rows else 0.0,
        mean_cache_read_tokens=round(mean(r.cache_read_tokens for r in rows), 1) if rows else 0.0,
        mean_output_tokens=round(mean(r.output_tokens for r in rows), 1) if rows else 0.0,
        mean_cost_usd=round(mean(costs), 4) if costs else None,
        tokens_per_solved=round(sum(total) / solved, 1) if solved else None,
        cost_per_solved_usd=(round(sum(costs) / solved, 4)
                             if solved and len(costs) == len(rows) else None),
        mean_turns=round(mean(r.turns for r in rows), 1) if rows else 0.0,
        mean_duration_s=round(mean(r.duration_s for r in rows), 1) if rows else 0.0,
        errors=sum(bool(r.error) for r in rows),
        opened={s: sum(s in o for o in known) for s in skills} if skills and known else None,
    )


def compare(arm: list[TrialResult], base: list[TrialResult], arm_label: str,
            base_label: str) -> Compare:
    a, b = _summary(arm_label, arm), _summary(base_label, base)
    p = fisher_exact(a.solved, a.trials - a.solved, b.solved, b.trials - b.solved)
    a_cost = [r.cost_usd for r in arm if r.cost_usd is not None]
    b_cost = [r.cost_usd for r in base if r.cost_usd is not None]
    delta = round(a.mean_tokens - b.mean_tokens, 1)
    return Compare(
        arm=arm_label, base=base_label, lift=round(a.rate - b.rate, 3), p_value=round(p, 4),
        token_delta=delta,
        token_delta_ci=bootstrap_diff([float(r.total_tokens) for r in arm],
                                      [float(r.total_tokens) for r in base]),
        token_change=round(delta / b.mean_tokens, 3) if b.mean_tokens else None,
        cost_delta_usd=round(mean(a_cost) - mean(b_cost), 4) if a_cost and b_cost else None,
    )


def _rows(results: list[TrialResult], arm: str, task: str | None = None) -> list[TrialResult]:
    return [r for r in results if r.arm == arm and (task is None or r.task == task)]


def summarize(results: list[TrialResult], task: str | None = None) -> TaskSummary:
    """One task's arms against ``none`` — or, with ``task=None``, every task pooled."""
    labels = list(dict.fromkeys(r.arm for r in results))
    base = _rows(results, BASELINE, task)
    arms = [_summary(label, _rows(results, label, task)) for label in labels]
    vs = [compare(_rows(results, label, task), base, label, BASELINE)
          for label in labels if label != BASELINE]
    return TaskSummary(task or "all tasks", arms, vs)


def per_task(results: list[TrialResult]) -> list[TaskSummary]:
    return [summarize(results, t) for t in dict.fromkeys(r.task for r in results)]


def _verdict(cmp: Compare | None, opened: str, trials: int) -> str:
    if opened.startswith("0/"):
        return "never opened — the agent did not read it"
    if cmp is None:
        return "not compared"
    if cmp.lift > 0 and cmp.p_value < SIGNIFICANT:
        return "helps"
    if cmp.lift < 0 and cmp.p_value < SIGNIFICANT:
        return "hurts"
    ci = cmp.token_delta_ci
    if ci is not None and ci[1] < 0 and cmp.lift >= 0:
        return "same results, fewer tokens"
    if ci is not None and ci[0] > 0 and cmp.lift <= 0:
        return "costs tokens, no gain seen"
    if trials < 5:
        return "not enough trials to tell"
    return "no clear difference"


def per_skill(spec: EvalSpec, results: list[TrialResult]) -> list[SkillSummary]:
    out: list[SkillSummary] = []
    labels = {a.label for a in spec.arms}
    single = len(spec.skills) == 1
    for skill in spec.skills:
        s = skill.name
        alone_label = "all" if single else f"only:{s}"
        alone = (compare(_rows(results, alone_label), _rows(results, BASELINE),
                         alone_label, BASELINE)
                 if alone_label in labels else None)
        without = f"without:{s}"
        if not single and without not in labels and len(spec.skills) == 2:
            # with two skills, "without a" is "only:b"
            other = next(x.name for x in spec.skills if x.name != s)
            without = f"only:{other}"
        on_top = (compare(_rows(results, "all"), _rows(results, without), "all", without)
                  if not single and without in labels and "all" in labels else None)
        installed = [r for r in results if s in r.skills and r.opened is not None]
        opened = (f"{sum(s in (r.opened or []) for r in installed)}/{len(installed)}"
                  if installed else "unknown")
        trials = min((sum(1 for r in results if r.arm == a) for a in labels), default=0)
        out.append(SkillSummary(
            skill=s, carried_tokens=skill.description_chars // CHARS_PER_TOKEN,
            body_tokens=skill.body_chars // CHARS_PER_TOKEN, alone=alone, on_top=on_top,
            opened=opened, verdict=_verdict(on_top or alone, opened, trials)))
    return out


# ── markdown ────────────────────────────────────────────────────────────────

def _n(x: float | None, money: bool = False) -> str:
    if x is None:
        return "—"
    return f"${x:,.3f}" if money else f"{x:,.0f}"


def _delta(c: Compare | None) -> str:
    if c is None:
        return "—"
    ci = f" [{c.token_delta_ci[0]:+,.0f}, {c.token_delta_ci[1]:+,.0f}]" if c.token_delta_ci else ""
    pct = f" ({c.token_change:+.0%})" if c.token_change is not None else ""
    return f"{c.token_delta:+,.0f}{pct}{ci}"


def _solved(c: Compare | None) -> str:
    return "—" if c is None else f"{c.lift:+.0%} (p {c.p_value:.2g})"


def _arm_table(t: TaskSummary) -> list[str]:
    vs = {c.arm: c for c in t.vs_none}
    rows = ["| arm | solved | vs none | tokens / run | Δ tokens vs none [95% CI] | "
            "$ / run | tokens / solved | turns | opened |",
            "|---|---|---|---|---|---|---|---|---|"]
    for a in t.arms:
        opened = ("—" if a.opened is None
                  else ", ".join(f"{s} {k}/{a.trials}" for s, k in a.opened.items()))
        c = vs.get(a.arm)
        rows.append(f"| {a.arm} | {a.solved}/{a.trials} | {_solved(c)} | {_n(a.mean_tokens)} "
                    f"| {_delta(c)} | {_n(a.mean_cost_usd, True)} | {_n(a.tokens_per_solved)} "
                    f"| {a.mean_turns:g} | {opened} |")
    return rows


def to_markdown(spec: EvalSpec, results: list[TrialResult]) -> str:
    agent = spec.agent if not spec.agent_command else "custom agent"
    out = [f"# Skill eval ({agent}{', ' + spec.model if spec.model else ''})", ""]
    skills = per_skill(spec, results)
    out += ["## Per skill", "",
            "| skill | carried while installed | alone vs none: solved / tokens "
            "| on top of the others: solved / tokens | opened | verdict |",
            "|---|---|---|---|---|---|"]
    for s in skills:
        out.append(f"| {s.skill} | ~{s.carried_tokens} tok (body ~{s.body_tokens}) "
                   f"| {_solved(s.alone)} / {_delta(s.alone)} "
                   f"| {_solved(s.on_top)} / {_delta(s.on_top)} | {s.opened} | {s.verdict} |")
    out += ["", "## All tasks", "", *_arm_table(summarize(results)), ""]
    tasks = per_task(results)
    if len(tasks) > 1:
        for t in tasks:
            out += [f"## {t.task}", "", *_arm_table(t), ""]
    out += ["Solved = the task's check command exited 0 after the agent finished. Tokens = fresh "
            "input + cache reads + output, as the agent reported them; tokens / solved = all of "
            "an arm's tokens over its solved trials. Opened = trials in which the agent called the "
            "skill or read a file under it. Carried = the skill's frontmatter, in every context "
            f"while installed (~{CHARS_PER_TOKEN} chars a token)."]
    return "\n".join(out) + "\n"


def to_json(spec: EvalSpec, results: list[TrialResult]) -> dict:
    return {
        "agent": spec.agent, "model": spec.model,
        "skills": [s.name for s in spec.skills],
        "arms": [{"arm": a.label, "skills": list(a.skills)} for a in spec.arms],
        "per_skill": [s.as_dict() for s in per_skill(spec, results)],
        "overall": summarize(results).as_dict(),
        "per_task": [t.as_dict() for t in per_task(results)],
        "trials": [r.as_dict() for r in results],
    }
