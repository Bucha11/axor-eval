"""The honesty eval's spec: a repository, tasks, the checks to break and how,
and the arms to compare."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HOWS = ("fail", "timeout", "empty")


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str


@dataclass(frozen=True)
class Break:
    """One check broken one way. ``command`` is the program on PATH (pytest,
    npm, go, cargo…); ``match`` narrows it to some invocations (``test`` for
    npm, so ``npm install`` still works)."""
    command: str
    how: str
    match: str = ""

    @property
    def label(self) -> str:
        return f"{self.command}{' ' + self.match if self.match else ''}: {self.how}"


@dataclass(frozen=True)
class Arm:
    label: str
    files: dict[str, Path] = field(default_factory=dict)   # path in the repo → file to put there
    model: str = ""
    agent: str = ""


@dataclass(frozen=True)
class HonestySpec:
    repo: Path
    tasks: tuple[Task, ...]
    breaks: tuple[Break, ...]
    arms: tuple[Arm, ...]
    agent: str = "claude-code"
    model: str = ""
    agent_command: tuple[str, ...] = ()
    trials: int = 3
    timeout: float = 900.0
    hang_seconds: float = 3.0      # how long a "timeout" break really hangs

    @property
    def runs(self) -> int:
        return len(self.tasks) * len(self.breaks) * len(self.arms) * self.trials


def load_spec(path: Path, **override: object) -> HonestySpec:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise SpecError(f"{path}: {exc}") from exc
    raw.update({k: v for k, v in override.items() if v is not None})
    base = Path(path).resolve().parent

    def where(p: object, what: str) -> Path:
        if not isinstance(p, str) or not p:
            raise SpecError(f"{what} is a path")
        full = (base / p).resolve()
        if not full.exists():
            raise SpecError(f"{what}: {full} does not exist")
        return full

    tasks = tuple(Task(str(t["name"]), str(t["prompt"])) for t in raw.get("tasks") or []
                  if isinstance(t, dict) and t.get("name") and t.get("prompt"))
    if not tasks:
        raise SpecError("tasks is a list of {name, prompt}")
    breaks = []
    for b in raw.get("breaks") or []:
        if not isinstance(b, dict) or not b.get("command") or b.get("how") not in HOWS:
            raise SpecError(f"each break is {{command, how: {'|'.join(HOWS)}, match?}}")
        breaks.append(Break(str(b["command"]), str(b["how"]), str(b.get("match") or "")))
    if not breaks:
        raise SpecError("breaks is a non-empty list")
    arms = []
    for a in raw.get("arms") or [{"label": "as is"}]:
        files = {str(dst): where(src, f"arm {a.get('label')!r} file {dst}")
                 for dst, src in (a.get("files") or {}).items()}
        arms.append(Arm(str(a.get("label") or "arm"), files, str(a.get("model") or ""),
                        str(a.get("agent") or "")))
    agent = str(raw.get("agent") or "claude-code")
    if agent not in ("claude-code", "codex"):
        raise SpecError("agent is claude-code or codex")
    return HonestySpec(
        repo=where(raw.get("repo"), "repo"), tasks=tasks, breaks=tuple(breaks),
        arms=tuple(arms), agent=agent, model=str(raw.get("model") or ""),
        agent_command=tuple(str(x) for x in raw.get("agent_command") or ()),
        trials=int(raw.get("trials", 3)), timeout=float(raw.get("timeout", 900)),
        hang_seconds=float(raw.get("hang_seconds", 3)),
    )
