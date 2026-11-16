"""One trial: a fresh copy of the repository, the agent once, the check.

The two arms differ in exactly one thing — the skill folder is installed where
the agent looks for skills (``.claude/skills/<name>`` / ``.codex/skills/<name>``)
or it is not. Same prompt, same starting files, same model, same timeout.

What the agent did is read from its own output stream (``claude -p
--output-format stream-json`` / ``codex exec --json``): tokens, turns, and
whether it opened the skill — a ``Skill`` tool call, or a read of a file under
the skill's folder.
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
from dataclasses import asdict, dataclass
from pathlib import Path

from axor_eval.skills.spec import EvalSpec, Task

ARMS = ("without", "with")
_SKIP = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__",
                               ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox")
# Codex has no built-in skill discovery to rely on: both arms are told where
# project skills live, so the only difference stays the skill itself.
_CODEX_HINT = "\n\n(Project skills, if any, are in .codex/skills/<name>/SKILL.md.)"


@dataclass
class TrialResult:
    task: str
    arm: str
    trial: int
    solved: bool
    check_output: str
    duration_s: float
    input_tokens: int
    output_tokens: int
    turns: int
    skill_opened: bool | None     # None: the agent's output did not say
    answer: str
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def skills_dir(agent: str) -> str:
    return ".codex/skills" if agent == "codex" else ".claude/skills"


def prepare(repo: Path, into: Path, *, skill: Path | None, skill_name: str, agent: str) -> Path:
    """A throwaway copy of ``repo`` — a git repository of its own, so the agent
    sees a project — with the skill installed when there is one."""
    work = into / "repo"
    shutil.copytree(repo, work, ignore=_SKIP, symlinks=True)
    if skill is not None:
        shutil.copytree(skill, work / skills_dir(agent) / skill_name,
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
    output_tokens: int = 0
    turns: int = 0
    skill_opened: bool | None = None


def _usage(u: object) -> tuple[int, int]:
    if not isinstance(u, dict):
        return 0, 0
    inp = sum(int(u.get(k, 0) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                "cache_creation_input_tokens"))
    return inp, int(u.get("output_tokens", 0) or 0)


def _opens_skill(name: str, payload: dict, skill_path: str) -> bool:
    low = name.lower()
    if low == "skill":
        return True
    text = json.dumps(payload, ensure_ascii=False)
    return skill_path in text


def observe(stdout: str, *, skill_path: str) -> Observed:
    """What the agent did, from its JSON lines (Claude Code stream-json, Codex
    --json). Lines that are not JSON are ignored; a stream that never shows a
    tool call leaves ``skill_opened`` unknown rather than False."""
    seen = Observed()
    saw_tools = False
    opened = False
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
                    saw_tools = True
                    opened |= _opens_skill(str(block.get("name", "")),
                                           block.get("input") or {}, skill_path)
        elif kind == "result":
            seen.answer = str(ev.get("result", "") or seen.answer)
            seen.turns = int(ev.get("num_turns", 0) or 0)
            seen.input_tokens, seen.output_tokens = _usage(ev.get("usage"))
        elif kind in ("item.completed", "item.started"):  # Codex
            item = ev.get("item") or {}
            itype = item.get("type")
            if itype in ("command_execution", "file_change", "mcp_tool_call", "file_read"):
                saw_tools = True
                if kind == "item.completed":
                    seen.turns += 1
                opened |= _opens_skill(str(itype), item, skill_path)
            elif itype in ("agent_message", "assistant_message") and item.get("text"):
                seen.answer = str(item["text"])
        elif kind == "turn.completed":
            i, o = _usage(ev.get("usage"))
            seen.input_tokens += i
            seen.output_tokens += o
    if saw_tools:
        seen.skill_opened = opened
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


def run_trial(spec: EvalSpec, task: Task, arm: str, trial: int, *,
              keep: bool = False) -> TrialResult:
    assert arm in ARMS
    name = spec.skill_name
    tmp = Path(tempfile.mkdtemp(prefix=f"axor-skill-eval-{arm}-"))
    error = ""
    try:
        work = prepare(task.repo, tmp, skill=spec.skill if arm == "with" else None,
                       skill_name=name, agent=spec.agent)
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
        seen = observe(stdout, skill_path=f"{skills_dir(spec.agent)}/{name}")
        code, check_out = _shell(task.check, work, spec.check_timeout)
        return TrialResult(task.name, arm, trial, code == 0, check_out, round(duration, 2),
                           seen.input_tokens, seen.output_tokens, seen.turns,
                           seen.skill_opened if arm == "with" else None, seen.answer[:2000], error)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def run_eval(spec: EvalSpec, *, on_trial: Callable[[TrialResult], None] | None = None,
             tasks: Iterable[str] | None = None) -> list[TrialResult]:
    """Every task × arm × trial, the arms interleaved (without, with, without,
    …) so a drift over time — a rate limit, a model update — hits both."""
    wanted = set(tasks) if tasks else None
    results: list[TrialResult] = []
    for task in spec.tasks:
        if wanted is not None and task.name not in wanted:
            continue
        for trial in range(1, spec.trials + 1):
            for arm in ARMS:
                r = run_trial(spec, task, arm, trial)
                results.append(r)
                if on_trial is not None:
                    on_trial(r)
    return results


def describe(spec: EvalSpec) -> str:
    cmd = shlex.join(agent_argv(spec, "<prompt>"))
    return (f"skill {spec.skill_name} · {len(spec.tasks)} task(s) × {spec.trials} trial(s)"
            f" × 2 arms · agent: {cmd}")
