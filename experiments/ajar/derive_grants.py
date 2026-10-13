"""Derive grant_args mechanically from tool schemas — no hand selection.

The rule (fixed before E1, see docs): every argument of a sink is under the grant
unless it is rich syntax; an optional argument is checked when present.

Mechanical parts, all read from what the benchmark ships:

  sink          Ajar's measured side effect: a tool is a sink iff executing it
                with ground-truth args changes the environment (ToolSpec.side_effect
                == "WRITE"). Not from axor's taxonomy.
  rich syntax   a string argument whose own docstring names it as free content:
                body / content / subject / title / description / message / text.
  optional      not in the schema's `required`, or nullable.
  kind          from the JSON type and the docstring: IBAN -> iban, email -> email,
                amount / price -> money, other numbers -> number, an ID -> id,
                anything else -> string. Arrays take their element's kind.

`derive(specs)` returns {suite: {sink: {arg: kind}}}; `RULES` holds the rule and the
banking-derived refinement used for the held-out check.

    python derive_grants.py            # print the derived table and its diff to v2
"""
from __future__ import annotations

import re
import sys
from typing import Any, Callable

# Rich syntax: the docstring's head noun is free content ("The body of the email",
# "Subject of the transaction"). Anchored at the start, so "The recipient of the
# message" — a party, not content — is not rich.
RICH = re.compile(r"^\s*(the\s+)?(body|content|subject|title|description|message|text)\b", re.I)


def _types(p: dict) -> set[str]:
    if "type" in p:
        t = p["type"]
        return set(t) if isinstance(t, list) else {t}
    return {x.get("type") for x in p.get("anyOf", []) if x.get("type")}


def kind_of(arg: str, p: dict) -> str:
    desc = (p.get("description") or "").split("\n")[0]
    text = f"{arg} {desc}"
    if re.search(r"\bIBAN\b", text):
        return "iban"
    t = _types(p) - {"null"}
    if t & {"number", "integer"}:
        return "money" if re.search(r"\b(amount|price)\b", text, re.I) else "number"
    if re.search(r"(^|_)id$", arg) or re.match(r"\s*(the\s+)?id\b", desc, re.I):
        return "id"
    if re.search(r"(^|_)e-?mail$", arg) or re.search(r"e-?mail address", desc, re.I) \
            or re.match(r"\s*(the\s+)?e-?mail\b", desc, re.I):
        return "email"
    return "string"


def is_rich(arg: str, p: dict) -> bool:
    if not (_types(p) - {"null"}) <= {"string"}:
        return False
    desc = (p.get("description") or "").split("\n")[0]
    return bool(RICH.search(desc))


def is_optional(arg: str, p: dict, required: set[str]) -> bool:
    return arg not in required or "null" in _types(p)


def rule_all_non_rich(arg: str, p: dict) -> bool:
    """The rule as stated: every non-rich argument."""
    return True


def rule_parties_and_magnitudes(arg: str, p: dict) -> bool:
    """Banking-derived refinement (see the banking diagnosis in the README): drop
    scheduling and flag arguments — dates, times, booleans — which a request rarely
    spells and which carry neither a party nor an amount."""
    desc = (p.get("description") or "").split("\n")[0]
    if _types(p) - {"null"} <= {"boolean"}:
        return False
    if re.search(r"\b(date|day|time)\b", f"{arg} {desc}", re.I) and not re.search(r"\bID\b", desc):
        return False
    return True


RULES: dict[str, Callable[[str, dict], bool]] = {
    "R0 all non-rich": rule_all_non_rich,
    "R1 parties+magnitudes (banking-derived)": rule_parties_and_magnitudes,
}


def derive(specs: dict, rule: Callable[[str, dict], bool] = rule_all_non_rich) -> dict:
    out: dict[str, dict[str, dict[str, str]]] = {}
    for key, spec in specs.items():
        suite = out.setdefault(key.suite, {})
        for t in spec.tools:
            if t.side_effect != "WRITE" or t.name in suite:
                continue
            props = t.params_schema.get("properties", {})
            req = set(t.params_schema.get("required", []))
            args = {}
            for a, p in props.items():
                if is_rich(a, p) or not rule(a, p):
                    continue
                k = kind_of(a, p)
                args[a] = k + ("?" if is_optional(a, p, req) else "")
            if args:
                suite[t.name] = args
    return out


def diff(a: dict, b: dict) -> list[str]:
    lines = []
    for suite in sorted(set(a) | set(b)):
        for sink in sorted(set(a.get(suite, {})) | set(b.get(suite, {}))):
            x, y = a.get(suite, {}).get(sink, {}), b.get(suite, {}).get(sink, {})
            if x != y:
                lines.append(f"{suite}.{sink}: derived={x} v2={y}")
    return lines


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import axor_ajar
    from ajar import io, paths

    specs = io.load_specs(paths.benchmark_data_dir("agentdojo", None) / "tasks.jsonl")
    for name, rule in RULES.items():
        d = derive(specs, rule)
        print(f"== {name}")
        for suite, sinks in sorted(d.items()):
            for sink, args in sorted(sinks.items()):
                print(f"  {suite:9s} {sink:32s} {args}")
        dd = diff(d, axor_ajar.GRANT_ARGS_V2)
        print(f"  -- differs from v2 on {len(dd)} sinks:")
        for line in dd:
            print("    " + line)
