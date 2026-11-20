"""The pieces of a team's coding-agent setup, each one removable on its own:
every installed skill, every section of the instructions file (CLAUDE.md for
Claude Code, AGENTS.md for Codex)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fragment:
    id: str            # "skill:deploy-helper", "CLAUDE.md#Deploying"
    kind: str          # skill | instructions
    name: str
    source: Path       # the skill's folder, or the instructions file
    text: str = ""     # an instructions section's own text

    @property
    def words(self) -> str:
        return (f"the skill {self.name}" if self.kind == "skill"
                else f"the section “{self.name}” of {self.source.name}")


def instructions_file(agent: str) -> str:
    return "AGENTS.md" if agent == "codex" else "CLAUDE.md"


def skills_root(agent: str) -> str:
    return ".codex/skills" if agent == "codex" else ".claude/skills"


def _sections(path: Path) -> list[tuple[str, str]]:
    """(title, text) per `## ` section; what comes before the first is "intro"."""
    out: list[tuple[str, str]] = []
    title, lines = "intro", []
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


def install(frags: list[Fragment], work: Path, agent: str) -> None:
    """Put these pieces of the setup into a sandbox copy."""
    sections = [f.text for f in frags if f.kind == "instructions"]
    if sections:
        (work / instructions_file(agent)).write_text("".join(sections))
    for f in frags:
        if f.kind == "skill":
            shutil.copytree(f.source, work / skills_root(agent) / f.name,
                            ignore=shutil.ignore_patterns(".git"), dirs_exist_ok=True)
