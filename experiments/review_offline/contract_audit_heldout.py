"""Held-out contract audit: LangChain community tools, vocabulary frozen.

The contract vocabulary was extended twice while auditing AgentDojo
(falsy_is_absent, structured). This audit runs on a toolset it was not shaped
on — every BaseTool subclass in ``langchain_community.tools`` whose ``_run`` is
inspectable — and adds detectors for behaviours AgentDojo did not exhibit:

  kwargs_passthrough  ``**kwargs`` reaches the effect: the field set is open, which
                      a closed contract cannot state (NOT expressible)
  shape_polymorphic   ``isinstance(p, ...)`` branch: one field accepted in several
                      shapes (a str or a list); a contract fixes one shape and
                      refuses the other (expressible, at a utility cost)

plus the AgentDojo detectors (default, none_absent, falsy_absent, self_parse,
coerced). Reports per behaviour, and which parameters no contract can express.

Run: uv run --no-project --with langchain-community --with pyyaml \
       --with-editable ../axor-core python experiments/review_offline/contract_audit_heldout.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import textwrap
import typing
from collections import Counter

import contract_audit as A


def _tools():
    import langchain_community.tools as pkg
    from langchain_core.tools import BaseTool
    seen = {}
    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            mod = importlib.import_module(m.name)
        except Exception:
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (issubclass(cls, BaseTool) and cls is not BaseTool and "_run" in cls.__dict__
                    and cls.__module__ == mod.__name__):
                seen[f"{cls.__module__}.{cls.__name__}"] = cls
    return seen


def _extra(fn, names):
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    found = {n: set() for n in names}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance":
            a = node.args[0] if node.args else None
            if isinstance(a, ast.Name) and a.id in found:
                found[a.id].add("shape_polymorphic")
    return found


def audit():
    rows = []
    for qual, cls in sorted(_tools().items()):
        fn = cls._run
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values()
                  if p.name not in ("self", "run_manager", "callbacks")]
        names = [p.name for p in params if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
        try:
            beh = A._body_behaviours(fn, names)
            ext = _extra(fn, names)
            hints = typing.get_type_hints(fn)
        except Exception:
            continue
        if any(p.kind is p.VAR_KEYWORD for p in params):
            rows.append((qual, "**kwargs", ["kwargs_passthrough"]))
        for p in params:
            if p.name not in names:
                continue
            b = set(beh[p.name]) | ext[p.name]
            if p.default is not inspect.Parameter.empty and p.default is not None:
                b.add("default")
            if p.default is None and not ({"none_absent", "falsy_absent"} & b):
                b.add("none_absent")
            if A._scalar(hints.get(p.name)) & {int, float, bool}:
                b.add("coerced")
            rows.append((qual, p.name, sorted(b)))
    return rows


if __name__ == "__main__":  # pragma: no cover
    rows = audit()
    tools = {r[0] for r in rows}
    hidden = [r for r in rows if r[2]]
    c = Counter(b for r in rows for b in r[2])
    not_expr = [r for r in rows if "kwargs_passthrough" in r[2]]
    print({"tools": len(tools), "parameters": len(rows), "with_hidden_behaviour": len(hidden),
           "behaviour_counts": dict(c), "not_expressible": len(not_expr)})
    for r in not_expr:
        print("  open field set:", r[0])
