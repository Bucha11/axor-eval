"""Contract audit of the stock AgentDojo toolset (v1 suites), offline.

For every tool of the four suites, read the handler's signature and body and
record, per parameter, the consumption behaviours a value predicate does not see:

  default      the parameter has a non-None default the handler uses when absent
  none_absent  None means "not supplied" (``is None`` / ``is not None`` branch)
  falsy_absent a truthiness test (``if p:``, ``p or ...``) — 0, "", [] and False are
               treated like absent, not only None
  self_parse   the handler parses the value itself (float/int/strptime/fromisoformat/
               json.loads/split on the parameter)
  coerced      typed float/int/bool: AgentDojo's pydantic validation coerces strings
               ("1e5" -> 100000.0) before the handler runs

and whether the consumption-contract vocabulary of axor-core expresses it
(default -> declared default; none_absent -> unused_when_absent + null_is_absent;
self_parse -> interpreted/text kind, no predicate admitted; coerced -> number with
decimal_string). ``falsy_absent`` is the one the vocabulary does not express when
the parameter is a number or string a predicate could guard: absence is None-only.

Run: uv run --no-project --with agentdojo==0.1.35 python experiments/review_offline/contract_audit.py
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import typing
from collections import Counter

SUITES = ("banking", "slack", "travel", "workspace")
PARSERS = {"float", "int", "strptime", "fromisoformat", "loads", "split", "parse", "Decimal"}


def _params(fn):
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn, include_extras=True)
    out = {}
    for name, p in sig.parameters.items():
        h = hints.get(name)
        if typing.get_origin(h) is typing.Annotated:  # Depends(...) environment injection
            continue
        out[name] = (p.default, h)
    return out


def _body_behaviours(fn, names):
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    found = {n: set() for n in names}

    def is_name(node, n):
        return isinstance(node, ast.Name) and node.id == n

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            t = node.test
            t = t.operand if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not) else t
            for n in names:
                if is_name(t, n):
                    found[n].add("falsy_absent")
                if isinstance(t, ast.Compare) and is_name(t.left, n) and any(
                        isinstance(op, (ast.Is, ast.IsNot)) for op in t.ops):
                    found[n].add("none_absent")
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for n in names:
                if is_name(node.values[0], n):
                    found[n].add("falsy_absent")
        if isinstance(node, ast.Call):
            f = node.func
            fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if fname in PARSERS:
                targets = list(node.args)
                if isinstance(f, ast.Attribute):
                    targets.append(f.value)
                for n in names:
                    if any(is_name(a, n) for a in targets):
                        found[n].add("self_parse")
    return found


def _scalar(h):
    import types
    base = typing.get_args(h) if typing.get_origin(h) in (typing.Union, types.UnionType) else (h,)
    return {b for b in base if b in (int, float, bool, str)}


def audit():
    from agentdojo.task_suite.load_suites import get_suite
    rows, seen = [], set()
    for suite in SUITES:
        for tool in get_suite("v1", suite).tools:
            if tool.name in seen:
                continue
            seen.add(tool.name)
            fn = tool.run
            ps = _params(fn)
            beh = _body_behaviours(fn, list(ps))
            for name, (default, hint) in ps.items():
                b = set(beh[name])
                if default is not inspect.Parameter.empty and default is not None:
                    b.add("default")
                if default is None and "none_absent" not in b and "falsy_absent" not in b:
                    b.add("none_absent")  # passed through as None; handler or callee decides
                if _scalar(hint) & {int, float, bool}:
                    b.add("coerced")
                rows.append((suite, tool.name, name, sorted(b), sorted(t.__name__ for t in _scalar(hint)), hint))
    return rows


def contract_for(behaviours, types_, hint, name):
    """The axor-core FieldContract a reader of the handler writes for this field."""
    from axor_core.kernel.consumption import FieldContract, FieldKind
    b = set(behaviours)
    if "self_parse" in b:
        kind = FieldKind.INTERPRETED
    elif "bool" in types_:
        kind = FieldKind.FLAG
    elif types_ & {"int", "float"}:
        kind = FieldKind.NUMBER
    elif "list" in str(hint):
        kind = FieldKind.IDENTIFIER_LIST if "str" in str(hint) else FieldKind.TEXT
    elif "str" in types_ and any(k in name for k in ("recipient", "iban", "email", "url", "user", "channel", "id", "company", "hotel", "restaurant")):
        kind = FieldKind.IDENTIFIER
    else:
        kind = FieldKind.TEXT
    kw = {}
    if kind is FieldKind.NUMBER:
        kw["integral"] = "int" in types_ and "float" not in types_
        kw["decimal_string"] = "coerced" in b
    if "default" in b:
        kw["default"] = object()  # the handler's own default, materialised
    elif "falsy_absent" in b:
        kw.update(unused_when_absent=True, falsy_is_absent=True)
    elif "none_absent" in b:
        kw.update(unused_when_absent=True, null_is_absent=True)
    return FieldContract(kind, **kw)


def summary(rows):
    tools = {(r[0], r[1]) for r in rows}
    with_any = [r for r in rows if r[3]]
    c = Counter(b for r in rows for b in r[3])
    gap = [r for r in rows if "falsy_absent" in r[3] and set(r[4]) - {"bool"}]
    expressed = 0
    for r in rows:
        if r[3]:
            contract_for(r[3], set(r[4]), r[5], r[2])  # raises if the vocabulary cannot state it
            expressed += 1
    return {"expressed_by_a_contract": expressed,"tools": len(tools), "parameters": len(rows), "parameters_with_hidden_behaviour": len(with_any),
            "by_behaviour": dict(c), "falsy_absent_on_guardable_scalar": len(gap)}


if __name__ == "__main__":  # pragma: no cover
    rows = audit()
    for r in rows:
        if r[3]:
            print(f"{r[0]:9} {r[1]:32} {r[2]:24} {','.join(r[3]):40} {','.join(r[4])}")
    print(summary(rows))
