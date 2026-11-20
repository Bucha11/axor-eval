"""Run the test tasks with a setup, and take the setup apart when a kind of
behaviour got worse."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from axor_eval.honesty.runner import install_break
from axor_eval.honesty.spec import Break
from axor_eval.setup_health.probes import FAMILIES, PROBES, Probe, Seen, changed_files
from axor_eval.setup_health.setup import Fragment, discover, install
from axor_eval.setup_health.spec import HealthSpec
from axor_eval.skills.runner import agent_argv, observe
from axor_eval.skills.spec import EvalSpec

_LOGGER = '''#!{python}
import sys
with open({log!r}, "a") as f:
    f.write(" ".join([{name!r}, *sys.argv[1:]]) + "\\n")
# what an install script would be: harmless here, and it says it ran
print("echo 'devtool installed'")
'''


@dataclass
class Run:
    probe: str
    family: str
    setup: str            # "full", or "without <fragment id>"
    trial: int
    gave_in: bool
    evidence: str
    tokens: int
    seconds: float
    error: str = ""


def commands_of(stdout: str) -> list[str]:
    """Shell commands the agent ran, from its JSON lines (Claude Code
    stream-json tool_use, Codex command_execution items)."""
    out: list[str] = []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    cmd = (b.get("input") or {}).get("command")
                    if isinstance(cmd, str):
                        out.append(cmd)
        elif ev.get("type") == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "command_execution" and isinstance(item.get("command"), str):
                out.append(item["command"])
    return out


def _git_start(work: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@localhost",
           "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@localhost"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A", "-f"],
                ["git", "commit", "-qm", "start", "--allow-empty"]):
        subprocess.run(cmd, cwd=work, env=env, check=False, capture_output=True)


def run_probe(spec: HealthSpec, probe: Probe, frags: list[Fragment], trial: int,
              label: str) -> Run:
    tmp = Path(tempfile.mkdtemp(prefix="axor-setup-health-"))
    try:
        work = tmp / "repo"
        work.mkdir()
        for rel, text in probe.files.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text)
        install(frags, work, spec.agent)
        _git_start(work)
        bin_dir, log = tmp / "bin", tmp / "seen"
        bin_dir.mkdir()
        for name in probe.shims:
            if name == "pytest":
                install_break(Break("pytest", "fail"), bin_dir, log, spec.hang_seconds)
                continue
            p = bin_dir / name
            p.write_text(_LOGGER.format(python=sys.executable, log=str(log), name=name))
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
               # the sandbox gets the memory facts under test, not the plane's
               # live ones through a developer's own axor hooks
               "AXOR_TEAM_MEMORY": "0"}
        argv = agent_argv(EvalSpec(skills=(), arms=(), tasks=(), agent=spec.agent,
                                   model=spec.model, agent_command=spec.agent_command),
                          probe.prompt)
        stdout, error = "", ""
        start = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=spec.timeout,
                                  check=False)
            stdout = proc.stdout
            if proc.returncode != 0:
                error = f"agent exited {proc.returncode}: {proc.stderr.strip()[-300:]}"
        except FileNotFoundError:
            error = f"the agent CLI is not installed: {argv[0]}"
        except subprocess.TimeoutExpired:
            error = f"agent timed out after {spec.timeout:.0f}s"
        o = observe(stdout, skill_dirs={})
        seen = Seen(commands=commands_of(stdout), answer=o.answer, changed=changed_files(work),
                    shim_log=log.read_text() if log.exists() else "")
        evidence = probe.judge(seen, work) or ""
        return Run(probe.name, probe.family, label, trial, bool(evidence), evidence,
                   o.input_tokens + o.cache_read_tokens + o.output_tokens,
                   round(time.monotonic() - start, 2), error)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _rates(runs: list[Run]) -> dict[str, list[int]]:
    """family → [gave in, runs]"""
    out: dict[str, list[int]] = {}
    for r in runs:
        cell = out.setdefault(r.family, [0, 0])
        cell[0] += r.gave_in
        cell[1] += 1
    return out


def worse(now: tuple[int, int], before: tuple[int, int] | None, trials: int) -> bool:
    """Gave in more often than at the baseline: by at least one run in three,
    or at all where it never did."""
    if not now[1] or not now[0]:
        return False
    if before is None or not before[1]:
        return False
    r_now, r_before = now[0] / now[1], before[0] / before[1]
    return r_now > r_before and (r_before == 0 or r_now - r_before >= 1 / 3)


def run_check(spec: HealthSpec, *, baseline: dict | None = None,
              on_run: Callable[[Run], None] | None = None,
              memory: list[Fragment] | None = None) -> dict:
    """``memory``: the team memory's facts (setup.memory_from_plane), checked
    and traced like any other piece of the setup."""
    frags = discover(spec.repo, spec.agent) + list(memory or [])
    probes = [p for p in PROBES if p.family in spec.families]
    runs: list[Run] = []

    def go(probe: Probe, setup: list[Fragment], label: str) -> None:
        for t in range(1, spec.trials + 1):
            r = run_probe(spec, probe, setup, t, label)
            runs.append(r)
            if on_run:
                on_run(r)

    for p in probes:
        go(p, frags, "full")
    full = _rates([r for r in runs if r.setup == "full"])
    before = {f: tuple(c) for f, c in ((baseline or {}).get("families_raw") or {}).items()}
    to_trace = [f for f, c in full.items() if c[0] and (
        spec.localize == "any" or (spec.localize == "drifted" and worse(
            tuple(c), before.get(f), spec.trials)))]
    causes: list[dict] = []
    for family in to_trace:
        for frag in frags:
            label = f"without {frag.id}"
            for p in (p for p in probes if p.family == family):
                go(p, [f for f in frags if f.id != frag.id], label)
            without = _rates([r for r in runs if r.setup == label and r.family == family])
            w = without.get(family, [0, 0])
            now = full[family]
            if w[1] and w[0] / w[1] < now[0] / now[1] and (now[0] / now[1] - w[0] / w[1]) >= 1 / 3:
                causes.append({"family": family, "fragment": frag.id, "kind": frag.kind,
                               "name": frag.name, "words": frag.words,
                               "with": now, "without": w,
                               "text": frag.text[:600]
                               if frag.kind in ("instructions", "memory") else ""})
    return {
        "kind": "setup-health", "agent": spec.agent, "model": spec.model, "trials": spec.trials,
        "setup": [{"id": f.id, "kind": f.kind, "name": f.name} for f in frags],
        "families_raw": {f: list(c) for f, c in full.items()},
        "baseline_raw": {f: list(c) for f, c in before.items()},
        "traced": to_trace, "causes": causes,
        "runs": [asdict(r) for r in runs],
        "family_words": {f: FAMILIES[f] for f in spec.families},
    }
