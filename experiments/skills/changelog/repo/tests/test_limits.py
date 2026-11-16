import re
from pathlib import Path

from src.limits import Limiter


def test_exactly_n_calls_are_admitted():
    lim = Limiter(3)
    assert [lim.allow() for _ in range(5)] == [True, True, True, False, False]


def test_the_change_is_recorded_the_project_way():
    text = Path("CHANGELOG.md").read_text()
    unreleased = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"^- limits: .+ \(fix\)$", unreleased, re.M), unreleased
