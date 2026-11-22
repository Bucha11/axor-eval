"""One's own skill lives in the repository (`.claude/skills/<name>`). Evaluating
it must not crash on the copy, and the "none" arm must not have it."""
from __future__ import annotations

from pathlib import Path

from axor_eval.skills.runner import prepare


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo-src"
    skill = repo / ".claude" / "skills" / "test-first"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: test-first\ndescription: d\n---\nwrite a test first\n")
    (repo / "app.py").write_text("x = 1\n")
    return repo


def test_the_none_arm_does_not_have_the_skill_the_repo_holds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    work = prepare(repo, tmp_path / "none", skills={}, agent="claude-code",
                   evaluated=("test-first",))
    assert (work / "app.py").exists()
    assert not (work / ".claude" / "skills" / "test-first").exists()


def test_the_skill_arm_has_it_once_without_a_crash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    folder = repo / ".claude" / "skills" / "test-first"
    work = prepare(repo, tmp_path / "all", skills={"test-first": folder}, agent="claude-code",
                   evaluated=("test-first",))
    assert (work / ".claude" / "skills" / "test-first" / "SKILL.md").exists()
