"""The pieces of a team's coding-agent setup, each one removable on its own:
every installed skill, every section of the instructions file (CLAUDE.md for
Claude Code, AGENTS.md for Codex), and every fact of the team's memory on the
Control Plane (what agents are given at session start)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Fragment:
    id: str            # "skill:deploy-helper", "CLAUDE.md#Deploying"
    kind: str          # skill | instructions
    name: str
    source: Path       # the skill's folder, or the instructions file
    text: str = ""     # an instructions section's own text; a memory fact's line
    label: str = ""    # a memory fact: the repository's name, as the plane says it

    @property
    def words(self) -> str:
        if self.kind == "skill":
            return f"the skill {self.name}"
        if self.kind == "memory":
            return f"the team memory fact “{self.name}”"
        return f"the section “{self.name}” of {self.source.name}"


def instructions_file(agent: str) -> str:
    return "AGENTS.md" if agent == "codex" else "CLAUDE.md"


def skills_root(agent: str) -> str:
    return ".codex/skills" if agent == "codex" else ".claude/skills"


def _sections(path: Path) -> list[tuple[str, str]]:
    """(title, text) per `## ` section; what comes before the first is "intro"."""
    out: list[tuple[str, str]] = []
    title, lines = "intro", list[str]()
    for line in path.read_text().splitlines(keepends=True):
        if line.startswith("## "):
            if "".join(lines).strip():
                out.append((title, "".join(lines)))
            title, lines = line[3:].strip(), [line]
        else:
            lines.append(line)
    if "".join(lines).strip():
        out.append((title, "".join(lines)))
    return out


def discover(repo: Path, agent: str) -> list[Fragment]:
    frags: list[Fragment] = []
    root = repo / skills_root(agent)
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
            frags.append(Fragment(f"skill:{d.name}", "skill", d.name, d))
    instr = repo / instructions_file(agent)
    if instr.is_file():
        for title, text in _sections(instr):
            frags.append(Fragment(f"{instr.name}#{title}", "instructions", title, instr, text))
    return frags


MEMORY_FILE = ".claude/axor-team-memory.json"


def memory_text(facts: list[Fragment]) -> str:
    """The text an agent is given — the same shape the plane renders."""
    label = facts[0].label if facts else ""
    head = (f"What your team's coding agents verifiably learned in {label or 'this repository'} "
            "(each from commands that passed in their sessions — Axor Control Plane):")
    return "\n".join([head, *(f"- {f.text}" for f in facts)])


def _install_memory(facts: list[Fragment], work: Path, agent: str) -> None:
    """Give the sandbox agent these facts the way the axor hooks do: Claude
    Code's SessionStart additionalContext. Codex gets them as a section of
    AGENTS.md — near, not the same channel (its hooks config differs by
    version)."""
    text = memory_text(facts)
    if agent == "codex":
        path = work / instructions_file(agent)
        prior = path.read_text() if path.exists() else ""
        path.write_text(prior + ("\n" if prior else "") + "## Team memory\n\n" + text + "\n")
        return
    (work / MEMORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    (work / MEMORY_FILE).write_text(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}}))
    settings_path = work / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except ValueError:
        settings = {}
    hooks = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    hooks.append({"hooks": [{"type": "command",
                             "command": f'cat "$CLAUDE_PROJECT_DIR/{MEMORY_FILE}"'}]})
    settings_path.write_text(json.dumps(settings, indent=2))


def install(frags: list[Fragment], work: Path, agent: str) -> None:
    """Put these pieces of the setup into a sandbox copy."""
    sections = [f.text for f in frags if f.kind == "instructions"]
    if sections:
        (work / instructions_file(agent)).write_text("".join(sections))
    facts = [f for f in frags if f.kind == "memory"]
    if facts:
        _install_memory(facts, work, agent)
    for f in frags:
        if f.kind == "skill":
            shutil.copytree(f.source, work / skills_root(agent) / f.name,
                            ignore=shutil.ignore_patterns(".git"), dirs_exist_ok=True)


# ── the team's memory, from the Control Plane ───────────────────────────────

def _normalize_remote(url: str) -> str:
    """As axor_wrap.agents.repo: one repository however it was cloned."""
    u = url.strip()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", u)
    u = re.sub(r":\d+/", "/", u)
    u = re.sub(r"\.git/?$", "", u).rstrip("/")
    return u.lower()


def repo_id(repo: Path) -> str:
    """The id the axor sidecar gives this repository."""
    try:
        from axor_wrap.agents.repo import repo_identity
    except ImportError:
        repo_identity = None
    if repo_identity is not None:
        return repo_identity(str(repo))[0]
    try:
        out = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=repo,
                             capture_output=True, text=True, timeout=2)
        remote = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        remote = ""
    if remote:
        return "r-" + hashlib.sha256(_normalize_remote(remote).encode()).hexdigest()[:16]
    return "p-" + hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]


class PlaneMemoryError(RuntimeError):
    pass


def memory_from_plane(repo: Path, plane_url: str, key: str = "", *,
                      timeout: float = 15.0) -> list[Fragment]:
    """Each fact the team's agents are given in this repository now, as a
    removable piece of the setup."""
    rid = repo_id(repo)
    req = urllib.request.Request(
        plane_url.rstrip("/") + f"/v1/coding/memory?repo={quote(rid, safe='')}",
        headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the user's plane
            body = json.loads(resp.read())
    except (OSError, ValueError) as exc:
        raise PlaneMemoryError(f"the team memory could not be read from the plane: {exc}") from exc
    label = str(body.get("label") or "")
    return [Fragment(f"memory:{i['id']}", "memory", str(i["text"]), Path("."), str(i["text"]),
                     label)
            for i in body.get("items") or [] if isinstance(i, dict) and "id" in i]
