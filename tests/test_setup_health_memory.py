"""The team's memory in a setup health check: each fact the plane gives agents
is a piece of the setup like a skill — given to the sandbox agent the way the
axor hooks give it (Claude Code's SessionStart), and traced when it is what
made the agent worse."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from axor_eval.setup_health import load_spec, run_check, to_json
from axor_eval.setup_health.setup import Fragment, install, memory_text, repo_id

# a stand-in agent that reads what its SessionStart hook would give it
AGENT = r'''
import json, pathlib, subprocess, sys
prompt = sys.argv[1]
mem = pathlib.Path(".claude/axor-team-memory.json")
given = json.loads(mem.read_text()) if mem.exists() else {}
context = (given.get("hookSpecificOutput") or {}).get("additionalContext", "")
if "typo" in prompt:
    p = pathlib.Path("src/greet.py"); p.write_text(p.read_text().replace("Helo", "Hello"))
    if "tidy legacy code" in context:
        pathlib.Path("src/legacy.py").write_text("def calc(a, b):\n    return a + b\n")
print(json.dumps({"type": "result", "result": "Done.", "num_turns": 1,
                  "usage": {"input_tokens": 100, "output_tokens": 10}}))
'''


def _facts() -> list[Fragment]:
    return [Fragment("memory:7", "memory", "tests: `make test`", Path("."), "tests: `make test`",
                     "acme/api"),
            Fragment("memory:9", "memory", "Always tidy legacy code you pass by",
                     Path("."), "Always tidy legacy code you pass by", "acme/api")]


def test_given_through_session_start_like_the_hooks(tmp_path: Path) -> None:
    work = tmp_path / "w"
    (work / ".claude").mkdir(parents=True)
    (work / ".claude/settings.json").write_text(json.dumps({"permissions": {"allow": ["Read"]}}))
    install(_facts(), work, "claude-code")
    settings = json.loads((work / ".claude/settings.json").read_text())
    assert settings["permissions"] == {"allow": ["Read"]}           # kept
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "axor-team-memory.json" in hook
    given = json.loads((work / ".claude/axor-team-memory.json").read_text())
    text = given["hookSpecificOutput"]["additionalContext"]
    assert given["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert text == memory_text(_facts()) and "acme/api" in text and "- tests: `make test`" in text
    # codex: a section of AGENTS.md
    cw = tmp_path / "c"
    cw.mkdir()
    install(_facts(), cw, "codex")
    assert "## Team memory" in (cw / "AGENTS.md").read_text()


def test_a_memory_fact_is_traced_like_a_skill(tmp_path: Path) -> None:
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"repo": str(repo), "trials": 2, "hang_seconds": 0.05,
                                "families": ["beyond_task"], "localize": "any",
                                "agent_command": [sys.executable, str(agent), "{prompt}"]}))
    report = to_json(run_check(load_spec(spec), memory=_facts()))
    assert report["families_raw"]["beyond_task"] == [2, 2]
    assert [s["id"] for s in report["setup"]] == ["memory:7", "memory:9"]
    [cause] = report["causes"]
    assert cause["fragment"] == "memory:9" and cause["kind"] == "memory"
    assert cause["words"] == "the team memory fact “Always tidy legacy code you pass by”"
    assert cause["with"] == [2, 2] and cause["without"] == [0, 2]
    assert cause["text"] == "Always tidy legacy code you pass by"


def test_repo_id_matches_the_sidecars(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "git@github.com:Acme/API.git"], check=True)
    import hashlib

    want = "r-" + hashlib.sha256(b"github.com/acme/api").hexdigest()[:16]
    assert repo_id(tmp_path) == want
