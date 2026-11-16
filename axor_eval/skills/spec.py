"""The eval spec: which skill, which starting repository, which tasks.

JSON (or YAML, when PyYAML is installed), paths relative to the spec file::

    {
      "skill": "./release-helper",
      "repo": "./fixture",
      "agent": "claude-code",
      "trials": 5,
      "timeout": 600,
      "tasks": [
        {"name": "changelog", "prompt": "Add a changelog entry for the fix in src/limits.py",
         "check": "python -m pytest -q tests/test_changelog.py"}
      ]
    }

A task may name its own ``repo``. ``check`` runs in the trial's workspace after
the agent finishes, through the shell: exit 0 means the task was solved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

AGENTS = ("claude-code", "codex")


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    check: str
    repo: Path


@dataclass(frozen=True)
class EvalSpec:
    skill: Path
    tasks: tuple[Task, ...]
    agent: str = "claude-code"
    model: str = ""
    trials: int = 3
    timeout: float = 600.0
    check_timeout: float = 300.0
    # a command to run instead of the agent CLI, for a custom agent (or a test
    # double): `{prompt}` and `{model}` are substituted
    agent_command: tuple[str, ...] = field(default_factory=tuple)

    @property
    def skill_name(self) -> str:
        return skill_name(self.skill)


def skill_name(folder: Path) -> str:
    """The skill's ``name:`` from SKILL.md's frontmatter, else its folder's."""
    md = next((p for p in folder.iterdir() if p.name.lower() == "skill.md"), None)
    if md is not None:
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            end = text.find("\n---", 3)
            for line in text[3:end if end > 0 else 0].splitlines():
                key, _, value = line.partition(":")
                if key.strip().lower() == "name" and value.strip():
                    return value.strip().strip("'\"")
    return folder.resolve().name


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
    """Read and validate a spec. ``override`` (trials, agent, model, timeout)
    wins over the file — the CLI's flags."""
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

    skill = where(data.get("skill"), "skill")
    if not any(p.name.lower() == "skill.md" for p in skill.iterdir()):
        raise SpecError(f"skill {skill} has no SKILL.md")
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
        skill=skill, tasks=tuple(tasks), agent=agent, model=str(values.get("model", "") or ""),
        trials=trials, timeout=float(values.get("timeout", 600)),
        check_timeout=float(values.get("check_timeout", 300)),
        agent_command=tuple(str(c) for c in command) if isinstance(command, (list, tuple)) else (),
    )
