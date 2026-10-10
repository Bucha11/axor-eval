#!/usr/bin/env python3
"""Does the AuthorityPolicy / ExecutionPlan split reach any enforcement path?

contracts/authority.py:17-19 states the position itself: "During the migration
window the legacy ExecutionPolicy (which mixes both concerns) remains the runtime
object; axor_core.policy.legacy converts between the models." This measures what
that leaves: which modules read the new types, and who calls the converter.

A paper claim resting on a completed planning/authority separation would need a
gate that reads AuthorityPolicy. The point of the check is that none does.
"""
from __future__ import annotations

import ast
import configparser
import re
from pathlib import Path

from _corepath import say

CORE = Path(__file__).resolve().parents[4] / "axor-core"
PKG = CORE / "axor_core"

NEW_TYPES = ("AuthorityPolicy", "ChildAuthorityPolicy", "ExportAuthorityPolicy",
             "ExecutionPlan")
CONVERTERS = ("split_legacy_policy", "merge_to_legacy_policy")
DEFINING = {PKG / "contracts" / "authority.py", PKG / "contracts" / "planning.py",
            PKG / "policy" / "legacy.py"}
# Re-export surfaces: they publish the names, they do not act on them.
REEXPORTS = {PKG / "__init__.py", PKG / "contracts" / "__init__.py"}

readers: dict[str, list[str]] = {}
def identifiers(path: Path) -> set[str]:
    """Every identifier the module actually uses — names, attributes and imported
    symbols, via the AST, so a docstring or comment naming the target model does
    not count as a use of it."""
    tree = ast.parse(path.read_text())
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            used.update(a.name.rsplit(".", 1)[-1] for a in node.names)
            used.update(a.asname for a in node.names if a.asname)
        elif isinstance(node, ast.arg):
            used.add(node.annotation.id if isinstance(node.annotation, ast.Name) else "")
    return used


for path in sorted(PKG.rglob("*.py")):
    if path in DEFINING or path in REEXPORTS:
        continue
    hits = sorted(set(NEW_TYPES) & identifiers(path))
    if hits:
        readers[str(path.relative_to(CORE))] = hits

say("A1 no module outside the contracts and the converter reads the new types",
    not readers,
    f"readers={readers or 'none'} (re-export surfaces and prose mentions excluded; "
    "worker/session.py:90 names the split in a docstring only)")

callers: list[str] = []
for path in sorted(PKG.rglob("*.py")):
    if path in DEFINING or path in REEXPORTS:
        continue
    if set(CONVERTERS) & identifiers(path):
        callers.append(str(path.relative_to(CORE)))
say("A2 the converter has no runtime caller", not callers,
    f"callers={callers or 'none'}; it is exercised only by "
    "tests/contracts/test_authority_plan_split.py (round-trip)")

# What IS enforced: the import boundary, so planning cannot become authority.
cfg = configparser.ConfigParser()
cfg.read(CORE / ".importlinter")
contracts = [s.split(":", 2)[2] for s in cfg.sections() if s.startswith("importlinter:contract:")]
pinned = {"authority-plan-separation", "planning-non-authoritative"} <= set(contracts)
say("A3 the import boundary is pinned even though the model is unused", pinned,
    f"contracts present={sorted(set(contracts) & {'authority-plan-separation', 'planning-non-authoritative'})}")

# The runtime object, for the record.
runtime = len([p for p in PKG.rglob("*.py")
               if re.search(r"\bExecutionPolicy\b", p.read_text())])
print(f"      for scale: ExecutionPolicy is referenced in {runtime} modules under axor_core/")
