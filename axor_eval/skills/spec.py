"""The eval spec: which skills, which starting repository, which tasks, which arms.

JSON (or YAML, when PyYAML is installed), paths relative to the spec file::

    {
      "skills": ["./changelog-entries", "./test-first", "./release-notes"],
      "repo": "./fixture",
      "agent": "claude-code",
      "trials": 5,
      "arms": "ablation",
      "tasks": [
        {"name": "fix-and-record", "prompt": "…", "check": "python -m pytest -q"}
      ]
    }

``"skill": "./one"`` (a single skill) still works. ``arms`` says which skill
sets are compared, always against ``none`` (no skill installed):

- ``"ablation"`` (default): ``all``, each skill ``only:<s>``, and — with more
  than one — ``without:<s>`` (all but one). What a skill does alone, and what
  it adds on top of the others.
- ``"each"``: ``none``, ``all`` and ``only:<s>``.
- an explicit list of sets: ``[["a"], ["a", "b"]]``.

A task may name its own ``repo``. ``check`` runs in the trial's workspace after
the agent finishes, through the shell: exit 0 means the task was solved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

AGENTS = ("claude-code", "codex")
BASELINE = "none"


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    check: str
    repo: Path


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path

    @property
    def description_chars(self) -> int:
        """What the agent carries in context for an INSTALLED skill before it
        uses it: the frontmatter (name, description). The body is read only
        when the skill is used."""
        text = _skill_md(self.path).read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end > 0:
                return len(text[3:end].strip())
        return len(self.name)

    @property
    def body_chars(self) -> int:
        return len(_skill_md(self.path).read_text(encoding="utf-8", errors="replace"))


@dataclass(frozen=True)
class Arm:
    label: str
    skills: tuple[str, ...]


@dataclass(frozen=True)
class EvalSpec:
    skills: tuple[Skill, ...]
    tasks: tuple[Task, ...]
    arms: tuple[Arm, ...]
    agent: str = "claude-code"
    model: str = ""
    trials: int = 3
    timeout: float = 600.0
    check_timeout: float = 300.0
    # a command to run instead of the agent CLI, for a custom agent (or a test
    # double): `{prompt}` and `{model}` are substituted
    agent_command: tuple[str, ...] = field(default_factory=tuple)

    def skill(self, name: str) -> Skill:
        return next(s for s in self.skills if s.name == name)

    @property
    def runs(self) -> int:
        return len(self.tasks) * len(self.arms) * self.trials


def _skill_md(folder: Path) -> Path:
    md = next((p for p in folder.iterdir() if p.name.lower() == "skill.md"), None)
    if md is None:
        raise SpecError(f"skill {folder} has no SKILL.md")
    return md


def skill_name(folder: Path) -> str:
    """The skill's ``name:`` from SKILL.md's frontmatter, else its folder's."""
    text = _skill_md(folder).read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        for line in text[3:end if end > 0 else 0].splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "name" and value.strip():
                return value.strip().strip("'\"")
    return folder.resolve().name


def build_arms(names: list[str], how: object) -> tuple[Arm, ...]:
    """``none`` first, then the sets to compare with it — each set once."""
    arms: list[Arm] = [Arm(BASELINE, ())]
    if isinstance(how, list):
        for combo in how:
            if not isinstance(combo, list) or not combo:
                raise SpecError("an explicit arm is a non-empty list of skill names")
            unknown = [c for c in combo if c not in names]
            if unknown:
                raise SpecError(f"arm {combo}: unknown skill(s) {unknown}; known: {names}")
            arms.append(Arm("+".join(combo), tuple(combo)))
    else:
        mode = str(how or "ablation")
        if mode not in ("ablation", "each"):
            raise SpecError('arms must be "ablation", "each" or a list of skill sets')
        arms.append(Arm("all", tuple(names)))
        if len(names) > 1:
            arms += [Arm(f"only:{n}", (n,)) for n in names]
            # with two skills "without a" is "only b": the same set, run once
            if mode == "ablation" and len(names) > 2:
                arms += [Arm(f"without:{n}", tuple(x for x in names if x != n)) for n in names]
    seen: set[frozenset[str]] = set()
    unique: list[Arm] = []
    for arm in arms:
        key = frozenset(arm.skills)
        if key not in seen:
            seen.add(key)
            unique.append(arm)
    return tuple(unique)


class SpecError(ValueError):
    pass


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise SpecError("a YAML spec needs PyYAML; write it as JSON instead") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SpecError(f"{path}: the spec must be an object")
    return data


def load_spec(path: Path, **override: object) -> EvalSpec:
    """Read and validate a spec. ``override`` (trials, agent, model, timeout,
    agent_command) wins over the file — the CLI's flags."""
    path = path.resolve()
    data = _load(path)
    base = path.parent

    def where(raw: object, what: str) -> Path:
        if not isinstance(raw, str) or not raw:
            raise SpecError(f"{what} must be a path")
        p = (base / raw).resolve()
        if not p.is_dir():
            raise SpecError(f"{what} {raw!r} is not a folder")
        return p

    raw_skills = data.get("skills", [data["skill"]] if "skill" in data else None)
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SpecError('give "skills": [folders] (or "skill": folder)')
    skills: list[Skill] = []
    for i, raw in enumerate(raw_skills):
        folder = where(raw, f"skills[{i}]")
        skills.append(Skill(skill_name(folder), folder))
    names = [s.name for s in skills]
    if len(set(names)) != len(names):
        raise SpecError(f"two skills share a name: {names}")

    default_repo = data.get("repo")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise SpecError("tasks must be a non-empty list")
    tasks: list[Task] = []
    for i, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            raise SpecError(f"tasks[{i}] must be an object")
        name = str(t.get("name") or f"task-{i + 1}")
        prompt, check = t.get("prompt"), t.get("check")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SpecError(f"task {name!r} needs a prompt")
        if not isinstance(check, str) or not check.strip():
            raise SpecError(f"task {name!r} needs a check command (exit 0 = solved)")
        repo = where(t.get("repo", default_repo), f"task {name!r} repo")
        tasks.append(Task(name, prompt, check, repo))
    if len({t.name for t in tasks}) != len(tasks):
        raise SpecError("task names must be unique")

    values = {**data, **{k: v for k, v in override.items() if v is not None}}
    agent = str(values.get("agent", "claude-code"))
    command = values.get("agent_command") or ()
    if agent not in AGENTS and not command:
        raise SpecError(f"agent must be one of {', '.join(AGENTS)} (or give agent_command)")
    trials = int(values.get("trials", 3))
    if trials < 1:
        raise SpecError("trials must be at least 1")
    return EvalSpec(
        skills=tuple(skills), tasks=tuple(tasks), arms=build_arms(names, values.get("arms")),
        agent=agent, model=str(values.get("model", "") or ""),
        trials=trials, timeout=float(values.get("timeout", 600)),
        check_timeout=float(values.get("check_timeout", 300)),
        agent_command=tuple(str(c) for c in command) if isinstance(command, (list, tuple)) else (),
    )
