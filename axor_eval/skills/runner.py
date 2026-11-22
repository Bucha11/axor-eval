"""One trial: a fresh copy of the repository, a skill set installed, the agent
once, the check.

Arms differ in exactly one thing — which skill folders are installed where the
agent looks for skills (``.claude/skills/<name>`` / ``.codex/skills/<name>``).
Same prompt, same starting files, same model, same timeout.

What the agent did, and what it cost, is read from its own output stream
(``claude -p --output-format stream-json`` / ``codex exec --json``): input,
cache-read and output tokens, the reported cost, turns, and which skills it
opened — a ``Skill`` tool call naming one, or a read of a file under its folder.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from axor_eval.skills.spec import Arm, EvalSpec, Task

_SKIP = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__",
                               ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox")
# Codex has no built-in skill discovery to rely on: every arm is told where
# project skills live, so the only difference stays the skills themselves.
_CODEX_HINT = "\n\n(Project skills, if any, are in .codex/skills/<name>/SKILL.md.)"


@dataclass
class TrialResult:
    task: str
    arm: str
    skills: list[str]
    trial: int
    solved: bool
    check_output: str
    duration_s: float
    input_tokens: int           # fresh input, not counting cache reads
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float | None      # as the agent reported it; None when it does not
    turns: int
    opened: list[str] | None    # skills the agent opened; None: its output did not say
    answer: str
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {**asdict(self), "total_tokens": self.total_tokens}


def skills_dir(agent: str) -> str:
    return ".codex/skills" if agent == "codex" else ".claude/skills"


def prepare(repo: Path, into: Path, *, skills: dict[str, Path], agent: str,
            evaluated: tuple[str, ...] = ()) -> Path:
    """A throwaway copy of ``repo`` — a git repository of its own, so the agent
    sees a project — with the arm's skills installed. A skill under evaluation
    that the repository already holds (``./.claude/skills/<name>``, the usual
    place for one's own) is taken out of the copy first: the arm alone decides
    whether the agent has it — else "none" would run with it too."""
    work = into / "repo"
    shutil.copytree(repo, work, ignore=_SKIP, symlinks=True)
    for name in {*evaluated, *skills}:
        shutil.rmtree(work / skills_dir(agent) / name, ignore_errors=True)
    for name, folder in skills.items():
        shutil.copytree(folder, work / skills_dir(agent) / name,
                        ignore=shutil.ignore_patterns(".git"))
    if shutil.which("git"):
        env = {**os.environ, "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@localhost",
               "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@localhost"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "commit", "-qm", "start", "--allow-empty"]):
            subprocess.run(cmd, cwd=work, env=env, check=False, capture_output=True)
    return work


def agent_argv(spec: EvalSpec, prompt: str) -> list[str]:
    if spec.agent_command:
        return [part.replace("{prompt}", prompt).replace("{model}", spec.model)
                for part in spec.agent_command]
    if spec.agent == "claude-code":
        argv = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
                "--permission-mode", "bypassPermissions"]
        return argv + (["--model", spec.model] if spec.model else [])
    argv = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write"]
    return argv + (["-m", spec.model] if spec.model else []) + [prompt + _CODEX_HINT]


@dataclass
class Observed:
    answer: str = ""
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    turns: int = 0
    opened: set[str] | None = None
    _saw_tools: bool = field(default=False, repr=False)


def _add_usage(seen: Observed, u: object, *, replace: bool) -> None:
    if not isinstance(u, dict):
        return
    fresh = int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0)
    cached = int(u.get("cache_read_input_tokens", 0) or u.get("cached_input_tokens", 0) or 0)
    out = int(u.get("output_tokens", 0) or 0)
    if replace:
        seen.input_tokens, seen.cache_read_tokens, seen.output_tokens = fresh, cached, out
    else:
        seen.input_tokens += fresh
        seen.cache_read_tokens += cached
        seen.output_tokens += out


def _opened(tool: str, payload: dict, skill_dirs: dict[str, str]) -> set[str]:
    """Which skills one tool call opens: ``Skill`` naming one, or any path
    under a skill's folder in its arguments."""
    hit: set[str] = set()
    if tool.lower() == "skill":
        named = str(payload.get("skill") or payload.get("name") or payload.get("command") or "")
        hit |= {n for n in skill_dirs if n == named or named.startswith(n)}
    text = json.dumps(payload, ensure_ascii=False)
    hit |= {n for n, d in skill_dirs.items() if d in text}
    return hit


def observe(stdout: str, *, skill_dirs: dict[str, str]) -> Observed:
    """What the agent did and spent, from its JSON lines (Claude Code
    stream-json, Codex --json). Lines that are not JSON are ignored; a stream
    that never shows a tool call leaves ``opened`` unknown rather than empty."""
    seen = Observed()
    opened: set[str] = set()
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type")
        if kind == "assistant":                         # Claude Code
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    seen._saw_tools = True
                    opened |= _opened(str(block.get("name", "")), block.get("input") or {},
                                      skill_dirs)
        elif kind == "result":
            seen.answer = str(ev.get("result", "") or seen.answer)
            seen.turns = int(ev.get("num_turns", 0) or 0)
            _add_usage(seen, ev.get("usage"), replace=True)
            cost = ev.get("total_cost_usd", ev.get("cost_usd"))
            if isinstance(cost, (int, float)):
                seen.cost_usd = float(cost)
        elif kind in ("item.completed", "item.started"):  # Codex
            item = ev.get("item") or {}
            itype = item.get("type")
            if itype in ("command_execution", "file_change", "mcp_tool_call", "file_read"):
                seen._saw_tools = True
                if kind == "item.completed":
                    seen.turns += 1
                opened |= _opened(str(itype), item, skill_dirs)
            elif itype in ("agent_message", "assistant_message") and item.get("text"):
                seen.answer = str(item["text"])
        elif kind == "turn.completed":
            _add_usage(seen, ev.get("usage"), replace=False)
    if seen._saw_tools:
        seen.opened = opened
    return seen


def _shell(cmd: str, cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        # the spec's own check command, through the shell as written
        proc = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True,  # noqa: S602
                              text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"check timed out after {timeout:.0f}s"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode, out[-2000:]


def run_trial(spec: EvalSpec, task: Task, arm: Arm, trial: int, *,
              keep: bool = False) -> TrialResult:
    installed = {name: spec.skill(name).path for name in arm.skills}
    tmp = Path(tempfile.mkdtemp(prefix="axor-skill-eval-"))
    error = ""
    try:
        work = prepare(task.repo, tmp, skills=installed, agent=spec.agent,
                       evaluated=tuple(s.name for s in spec.skills))
        start = time.monotonic()
        try:
            proc = subprocess.run(agent_argv(spec, task.prompt), cwd=work,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=spec.timeout, check=False)
            stdout = proc.stdout
            if proc.returncode != 0:
                error = f"agent exited {proc.returncode}: {proc.stderr.strip()[-300:]}"
        except FileNotFoundError:
            stdout, error = "", f"the agent CLI is not installed: {agent_argv(spec, '')[0]}"
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout
            stdout = raw.decode(errors="replace") if isinstance(raw, bytes) else (raw or "")
            error = f"agent timed out after {spec.timeout:.0f}s"
        duration = time.monotonic() - start
        dirs = {n: f"{skills_dir(spec.agent)}/{n}" for n in installed}
        seen = observe(stdout, skill_dirs=dirs)
        code, check_out = _shell(task.check, work, spec.check_timeout)
        return TrialResult(
            task.name, arm.label, list(arm.skills), trial, code == 0, check_out,
            round(duration, 2), seen.input_tokens, seen.cache_read_tokens, seen.output_tokens,
            seen.cost_usd, seen.turns,
            sorted(seen.opened) if seen.opened is not None else None,
            seen.answer[:2000], error)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def run_eval(spec: EvalSpec, *, on_trial: Callable[[TrialResult], None] | None = None,
             tasks: Iterable[str] | None = None) -> list[TrialResult]:
    """Every task × trial × arm. The arms are interleaved, and their order
    rotates trial by trial, so drift over the run (a rate limit, a model
    update, a warm cache) does not land on one arm."""
    wanted = set(tasks) if tasks else None
    results: list[TrialResult] = []
    arms = list(spec.arms)
    for task in spec.tasks:
        if wanted is not None and task.name not in wanted:
            continue
        for trial in range(1, spec.trials + 1):
            shift = (trial - 1) % len(arms)
            for arm in arms[shift:] + arms[:shift]:
                r = run_trial(spec, task, arm, trial)
                results.append(r)
                if on_trial is not None:
                    on_trial(r)
    return results


def describe(spec: EvalSpec) -> str:
    cmd = shlex.join(agent_argv(spec, "<prompt>"))
    arms = ", ".join(a.label for a in spec.arms)
    return (f"{len(spec.skills)} skill(s) · arms: {arms} · {len(spec.tasks)} task(s)"
            f" × {spec.trials} trial(s) = {spec.runs} agent runs · agent: {cmd}")
