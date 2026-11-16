"""Which skills help, and what they cost? The ablation eval (axor_eval.skills),
run end to end on the shipped example with a scripted agent in place of Claude
Code. The example has three skills:

- changelog-entries — the one the task needs: with it read, the changelog line
  is in the project's form and the check passes;
- test-first — read and followed (an extra test, more tokens), but the check
  passes or fails the same either way: a cost with no gain;
- house-style — installed, never opened: it costs only its frontmatter.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from axor_eval.skills import load_spec, per_skill, run_eval, summarize, to_markdown
from axor_eval.skills.__main__ import main
from axor_eval.skills.report import bootstrap_diff, fisher_exact
from axor_eval.skills.runner import observe
from axor_eval.skills.spec import SpecError, build_arms

EXAMPLE = (Path(__file__).resolve().parents[1]
           / "experiments" / "skills" / "changelog" / "skill-eval.json")

# A stand-in for `claude -p … --output-format stream-json`: same output shape.
FAKE_AGENT = r'''
import json, pathlib
skills = {p.parent.name for p in pathlib.Path(".claude/skills").glob("*/SKILL.md")}
def emit(**ev): print(json.dumps(ev))
def tool(name, **inp): emit(type="assistant", message={"content": [
    {"type": "tool_use", "name": name, "input": inp}]})
emit(type="system", subtype="init")
fresh, cached, out = 1000 + 50 * len(skills), 200, 300   # every installed skill rides along
p = pathlib.Path("src/limits.py")
tool("Read", file_path=str(p))
p.write_text(p.read_text().replace("self.used > self.n", "self.used >= self.n"))
line = "- Fixed the limiter off-by-one"
if "changelog-entries" in skills:
    tool("Skill", skill="changelog-entries")
    line, fresh = "- limits: allow() now admits exactly n calls (fix)", fresh + 400
if "test-first" in skills:
    tool("Read", file_path=".claude/skills/test-first/SKILL.md")
    pathlib.Path("tests/test_regression.py").write_text("def test_ok():\n    assert True\n")
    fresh, out = fresh + 400, out + 200
c = pathlib.Path("CHANGELOG.md")
c.write_text(c.read_text().replace("## Unreleased\n", "## Unreleased\n\n" + line + "\n", 1))
emit(type="result", result="Fixed and recorded.", num_turns=4 + len(skills),
     total_cost_usd=round((fresh + out * 5) / 1e6, 6),
     usage={"input_tokens": fresh, "cache_read_input_tokens": cached, "output_tokens": out})
'''


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory):
    fake = tmp_path_factory.mktemp("agent") / "fake_agent.py"
    fake.write_text(FAKE_AGENT)
    spec = load_spec(EXAMPLE, trials=5, agent_command=[sys.executable, str(fake), "{prompt}"])
    return spec, run_eval(spec)


def test_the_arms_are_none_all_each_alone_and_all_but_one() -> None:
    spec = load_spec(EXAMPLE)
    assert [a.label for a in spec.arms] == [
        "none", "all", "only:changelog-entries", "only:test-first", "only:house-style",
        "without:changelog-entries", "without:test-first", "without:house-style"]
    assert spec.runs == 8 * 5
    # two skills: "without a" is "only b" — the same set is run once
    two = build_arms(["a", "b"], "ablation")
    assert [a.label for a in two] == ["none", "all", "only:a", "only:b"]
    assert [a.label for a in build_arms(["a"], None)] == ["none", "all"]
    assert [a.label for a in build_arms(["a", "b"], [["b", "a"]])] == ["none", "b+a"]


def test_each_skill_is_judged_alone_and_on_top_of_the_others(results) -> None:
    spec, rows = results
    skills = {s.skill: s for s in per_skill(spec, rows)}
    changelog, test_first, style = (skills["changelog-entries"], skills["test-first"],
                                    skills["house-style"])
    assert changelog.verdict == "helps"
    assert changelog.alone is not None and changelog.alone.lift == 1.0
    assert changelog.on_top is not None and changelog.on_top.lift == 1.0
    assert changelog.on_top.p_value < 0.01
    assert test_first.verdict == "costs tokens, no gain seen"
    assert test_first.on_top is not None and test_first.on_top.lift == 0.0
    assert test_first.on_top.token_delta == 650          # 400 in + 200 out + its 50 carried
    assert test_first.on_top.token_delta_ci == (650.0, 650.0)
    assert style.verdict.startswith("never opened") and style.opened == "0/20"
    assert style.carried_tokens > 0 and style.body_tokens > style.carried_tokens


def test_tokens_per_solved_and_cost_are_counted(results) -> None:
    _, rows = results
    arms = {a.arm: a for a in summarize(rows).arms}
    none, only_cl = arms["none"], arms["only:changelog-entries"]
    assert none.solved == 0 and none.tokens_per_solved is None      # nothing solved: no rate
    assert none.mean_tokens == 1500 and none.mean_cache_read_tokens == 200
    assert only_cl.solved == 5 and only_cl.tokens_per_solved == 1950
    assert only_cl.mean_cost_usd is not None and only_cl.cost_per_solved_usd is not None
    vs = {c.arm: c for c in summarize(rows).vs_none}
    assert vs["all"].token_delta == 1150
    assert vs["all"].token_change == pytest.approx(0.767, abs=1e-3)
    assert vs["all"].cost_delta_usd is not None and vs["all"].cost_delta_usd > 0


def test_the_report_and_the_cli(results, tmp_path: Path,
                                capsys: pytest.CaptureFixture[str]) -> None:
    spec, rows = results
    md = to_markdown(spec, rows)
    assert "| changelog-entries |" in md and "| helps |" in md
    assert "| none | 0/5 |" in md and "tokens / solved" in md
    fake = tmp_path / "fake_agent.py"
    fake.write_text(FAKE_AGENT)
    data = json.loads(EXAMPLE.read_text())
    data.update(skills=[str(EXAMPLE.parent / s) for s in ("changelog-entries", "test-first")],
                repo=str(EXAMPLE.parent / "repo"), arms="each",
                agent_command=[sys.executable, str(fake), "{prompt}"])
    spec_path, out, md_path = tmp_path / "spec.json", tmp_path / "r.json", tmp_path / "r.md"
    spec_path.write_text(json.dumps(data))
    assert main(["run", str(spec_path), "--trials", "1", "--out", str(out),
                 "--md", str(md_path)]) == 0
    report = json.loads(out.read_text())
    assert [a["arm"] for a in report["arms"]] == ["none", "all", "only:changelog-entries",
                                                  "only:test-first"]
    assert len(report["trials"]) == 4 and report["trials"][0]["total_tokens"] > 0
    err = capsys.readouterr().err
    assert "= 4 agent runs" in err and "opened changelog-entries, test-first" in err


def test_codex_output_is_read_too() -> None:
    lines = [
        {"type": "item.completed",
         "item": {"type": "command_execution",
                  "command": "cat .codex/skills/changelog-entries/SKILL.md"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        {"type": "turn.completed",
         "usage": {"input_tokens": 900, "cached_input_tokens": 300, "output_tokens": 80}},
    ]
    seen = observe("\n".join(json.dumps(x) for x in lines),
                   skill_dirs={"changelog-entries": ".codex/skills/changelog-entries",
                               "test-first": ".codex/skills/test-first"})
    assert (seen.answer, seen.input_tokens, seen.cache_read_tokens, seen.output_tokens) == (
        "done", 900, 300, 80)
    assert seen.opened == {"changelog-entries"} and seen.turns == 1
    assert observe("not json", skill_dirs={}).opened is None    # unknown, not "none"


def test_the_statistics_match_known_values() -> None:
    assert fisher_exact(3, 0, 0, 3) == pytest.approx(0.1)
    assert fisher_exact(5, 0, 0, 5) == pytest.approx(0.007937, abs=1e-5)
    assert fisher_exact(2, 1, 2, 1) == pytest.approx(1.0)
    assert bootstrap_diff([1.0], [2.0]) is None
    lo, hi = bootstrap_diff([10.0, 12.0, 11.0, 13.0], [1.0, 2.0, 1.0, 2.0]) or (0, 0)
    assert 7 < lo < hi < 13


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
    bad.write_text(json.dumps({"skills": ["./s"], "repo": ".", "arms": [["nope"]],
                               "tasks": [{"name": "t", "prompt": "p", "check": "true"}]}))
    with pytest.raises(SpecError, match="unknown skill"):
        load_spec(bad)
