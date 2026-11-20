"""What a setup health check runs: whose setup (a repository's skills and
instructions file), with which agent and model, how many times."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from axor_eval.setup_health.probes import FAMILIES


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class HealthSpec:
    repo: Path                       # where the team's setup lives
    agent: str = "claude-code"
    model: str = ""
    agent_command: tuple[str, ...] = ()
    trials: int = 3
    timeout: float = 600.0
    families: tuple[str, ...] = tuple(FAMILIES)
    # which kinds of behaviour to trace to a piece of the setup: those that got
    # worse since the baseline ("drifted"), any that gave in at all ("any"), none
    localize: str = "drifted"
    hang_seconds: float = 3.0


def load_spec(path: Path, **override: object) -> HealthSpec:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise SpecError(f"{path}: {exc}") from exc
    raw.update({k: v for k, v in override.items() if v is not None})
    repo = (Path(path).resolve().parent / str(raw.get("repo") or ".")).resolve()
    if not repo.is_dir():
        raise SpecError(f"repo: {repo} is not a directory")
    agent = str(raw.get("agent") or "claude-code")
    if agent not in ("claude-code", "codex"):
        raise SpecError("agent is claude-code or codex")
    fams = tuple(raw.get("families") or FAMILIES)
    unknown = [f for f in fams if f not in FAMILIES]
    if unknown:
        raise SpecError(f"unknown families {unknown}: one of {', '.join(FAMILIES)}")
    if raw.get("localize", "drifted") not in ("drifted", "any", "no"):
        raise SpecError("localize is drifted, any or no")
    return HealthSpec(repo=repo, agent=agent, model=str(raw.get("model") or ""),
                      agent_command=tuple(str(x) for x in raw.get("agent_command") or ()),
                      trials=int(raw.get("trials", 3)), timeout=float(raw.get("timeout", 600)),
                      families=fams, localize=str(raw.get("localize", "drifted")),
                      hang_seconds=float(raw.get("hang_seconds", 3)))
