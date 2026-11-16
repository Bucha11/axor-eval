"""Does a skill help? The A/B eval (axor_eval.skills), run end to end on the
shipped example with a scripted agent in place of Claude Code: it fixes the
bug either way, and writes the changelog line the project's way only when the
skill is installed and it read it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from axor_eval.skills import load_spec, run_eval, summarize, to_markdown
from axor_eval.skills.__main__ import main
from axor_eval.skills.report import fisher_exact, overall
from axor_eval.skills.runner import observe
from axor_eval.skills.spec import SpecError

EXAMPLE = (Path(__file__).resolve().parents[1]
           / "experiments" / "skills" / "changelog" / "skill-eval.json")

# A stand-in for `claude -p … --output-format stream-json`: same output shape.
FAKE_AGENT = r'''
import json, pathlib, sys
reads_skills = sys.argv[1] == "reads"
skill = next(iter(pathlib.Path(".claude/skills").glob("*/SKILL.md")), None)
def emit(**ev): print(json.dumps(ev))
emit(type="system", subtype="init")
p = pathlib.Path("src/limits.py")
read = {"type": "tool_use", "name": "Read", "input": {"file_path": str(p)}}
emit(type="assistant", message={"content": [read]})
p.write_text(p.read_text().replace("self.used > self.n", "self.used >= self.n"))
line = "- Fixed the limiter off-by-one"
if skill is not None and reads_skills:
    emit(type="assistant", message={"content": [{"type": "tool_use", "name": "Skill",
                                                 "input": {"skill": "changelog-entries"}}]})
    line = "- limits: allow() now admits exactly n calls (fix)"
c = pathlib.Path("CHANGELOG.md")
c.write_text(c.read_text().replace("## Unreleased\n", "## Unreleased\n\n" + line + "\n", 1))
emit(type="result", result="Fixed and recorded.", num_turns=4,
     usage={"input_tokens": 1200 if skill else 1000, "output_tokens": 300})
'''


@pytest.fixture
def fake_agent(tmp_path: Path) -> Path:
    path = tmp_path / "fake_agent.py"
    path.write_text(FAKE_AGENT)
    return path


def _spec(fake: Path, mode: str = "reads", trials: int = 3):
    return load_spec(EXAMPLE, trials=trials,
                     agent_command=[sys.executable, str(fake), mode, "{prompt}"])


def test_the_skill_that_is_read_and_followed_helps(fake_agent: Path) -> None:
    results = run_eval(_spec(fake_agent, trials=5))
    assert len(results) == 10
    [s] = summarize(results)
    assert (s.with_skill.solved, s.without.solved) == (5, 0)
    assert s.lift == 1.0 and s.p_value < 0.01 and s.verdict == "helps"
    assert s.with_skill.skill_opened == 5 and s.without.skill_opened is None
    assert s.with_skill.mean_input_tokens == 1200 and s.without.mean_input_tokens == 1000
    # the arms differ only in the skill: the "without" failure is the changelog
    fails = [r for r in results if r.arm == "without"]
    assert all("test_the_change_is_recorded_the_project_way" in r.check_output for r in fails)
    assert "- limits: .+ \\(fix\\)" not in to_markdown("x", "y", [s])   # a table, not a dump


def test_three_trials_a_side_is_not_called_an_effect(fake_agent: Path) -> None:
    [s] = summarize(run_eval(_spec(fake_agent, trials=3)))
    assert (s.with_skill.solved, s.without.solved) == (3, 0)
    assert s.p_value == pytest.approx(0.1)
    assert s.verdict == "not enough trials to tell"


def test_a_skill_the_agent_never_opens_gets_no_credit(fake_agent: Path) -> None:
    [s] = summarize(run_eval(_spec(fake_agent, mode="ignores", trials=2)))
    assert s.with_skill.skill_opened == 0
    assert s.verdict.startswith("never opened")


def test_the_cli_writes_the_table_and_every_trial(
        fake_agent: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = json.loads(EXAMPLE.read_text())
    spec.update(skill=str(EXAMPLE.parent / "skill"), repo=str(EXAMPLE.parent / "repo"),
                agent_command=[sys.executable, str(fake_agent), "reads", "{prompt}"])
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert main(["run", str(path), "--trials", "1", "--out", str(out), "--md", str(md)]) == 0
    report = json.loads(out.read_text())
    assert report["overall"] == {"with": "1/1", "without": "0/1", "lift": 1.0, "p_value": 1.0}
    assert len(report["trials"]) == 2
    assert "| fix-and-record | 0/1 | 1/1 | +100% |" in md.read_text()
    err = capsys.readouterr().err
    assert "fix-and-record · with    · trial 1: solved · opened the skill" in err


def test_codex_output_is_read_too() -> None:
    lines = [
        {"type": "item.completed",
         "item": {"type": "command_execution",
                  "command": "cat .codex/skills/changelog-entries/SKILL.md"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        {"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 80}},
    ]
    seen = observe("\n".join(json.dumps(x) for x in lines),
                   skill_path=".codex/skills/changelog-entries")
    assert (seen.answer, seen.input_tokens, seen.output_tokens, seen.turns) == ("done", 900, 80, 1)
    assert seen.skill_opened is True
    assert observe("not json", skill_path="x").skill_opened is None   # unknown, not "no"


def test_fisher_exact_matches_known_values() -> None:
    assert fisher_exact(3, 0, 0, 3) == pytest.approx(0.1)
    assert fisher_exact(5, 0, 0, 5) == pytest.approx(0.007937, abs=1e-5)
    assert fisher_exact(2, 1, 2, 1) == pytest.approx(1.0)
    assert overall([]) == {"with": "0/0", "without": "0/0", "lift": 0.0, "p_value": 1.0}


def test_a_spec_says_what_is_wrong(tmp_path: Path) -> None:
    (tmp_path / "s").mkdir()
    bad = tmp_path / "spec.json"
    tasks = [{"name": "t", "prompt": "p"}]
    bad.write_text(json.dumps({"skill": "./s", "repo": ".", "tasks": tasks}))
    with pytest.raises(SpecError, match="no SKILL.md"):
        load_spec(bad)
    (tmp_path / "s" / "SKILL.md").write_text("# s")
    with pytest.raises(SpecError, match="needs a check command"):
        load_spec(bad)
