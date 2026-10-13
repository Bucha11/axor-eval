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

import os
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


# ── the sink taxonomy, by rule ────────────────────────────────────────────────
#
#   sink       a tool whose execution changes the environment (Ajar's measured
#              side effect; a fetched URL is logged, so get_webpage is one)
#   egress     a sink with a destination argument: an email address, a URL, a
#              recipient, participants or a channel; every other sink is integrity
#   driving    the sink's non-rich arguments that name a party or an object:
#              numbers, dates/times and flags are excluded

DESTINATION = re.compile(r"(^|_)(recipients?|participants|channel|url|e-?mail|user_email|cc|bcc)$")


def _is_temporal(arg: str, p: dict) -> bool:
    desc = (p.get("description") or "").split("\n")[0]
    return bool(re.search(r"\b(date|day|time)\b", f"{arg} {desc}", re.I)) and not re.search(r"\bID\b", desc)


def derive_taxonomy(specs: dict) -> dict:
    out: dict[str, dict] = {}
    for key, spec in specs.items():
        t_suite = out.setdefault(key.suite, {"egress_sinks": set(), "integrity_sinks": set(), "driving_args": {}})
        for t in spec.tools:
            if t.side_effect != "WRITE":
                continue
            props = t.params_schema.get("properties", {})
            driving = []
            dest = False
            for a, p in props.items():
                if is_rich(a, p):
                    continue
                types = _types(p) - {"null"}
                if DESTINATION.search(a) or kind_of(a, p) == "email":
                    dest = True
                if types & {"number", "integer", "boolean"} or _is_temporal(a, p):
                    continue
                driving.append(a)
            (t_suite["egress_sinks"] if dest else t_suite["integrity_sinks"]).add(t.name)
            if driving:
                t_suite["driving_args"][t.name] = sorted(driving)
    return out


def taxonomy_diff(rule: dict, config_dir: str) -> list[str]:
    import yaml
    lines = []
    for suite, r in sorted(rule.items()):
        hand = yaml.safe_load(open(os.path.join(config_dir, f"{suite}.yaml")))
        for key in ("egress_sinks", "integrity_sinks"):
            a, b = set(r[key]), set(hand.get(key) or ())
            if a != b:
                lines.append(f"{suite}.{key}: rule-only={sorted(a - b)} hand-only={sorted(b - a)}")
        hd = {k: sorted(v) for k, v in (hand.get("driving_args") or {}).items()}
        for sink in sorted(set(r["driving_args"]) | set(hd)):
            if r["driving_args"].get(sink) != hd.get(sink):
                lines.append(f"{suite}.driving_args.{sink}: rule={r['driving_args'].get(sink)} hand={hd.get(sink)}")
    return lines


# Access control: a sink with an argument that names a credential (its own name or
# docstring) changes who can act as the user — L3/L4 grants only, never L1/L2.
CREDENTIAL = re.compile(r"(password|passphrase|\bpin\b|token|secret|credential|api[_ ]?key)", re.I)


def derive_access_control(specs: dict) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for key, spec in specs.items():
        for t in spec.tools:
            if t.side_effect != "WRITE":
                continue
            for a, p in t.params_schema.get("properties", {}).items():
                if CREDENTIAL.search(a) or CREDENTIAL.search((p.get("description") or "").split("\n")[0]):
                    out.setdefault(key.suite, set()).add(t.name)
    return {s: sorted(v) for s, v in out.items()}


def write_rule_configs(rule: dict, config_dir: str, out_dir: str, access_control: dict | None = None) -> None:
    """The hand configs with their sink declarations replaced by the rule's
    (sources and consequence overrides are kept as the operator wrote them)."""
    import yaml
    os.makedirs(out_dir, exist_ok=True)
    for suite, r in rule.items():
        hand = yaml.safe_load(open(os.path.join(config_dir, f"{suite}.yaml")))
        hand["egress_sinks"] = sorted(r["egress_sinks"])
        hand["integrity_sinks"] = sorted(r["integrity_sinks"])
        hand["driving_args"] = r["driving_args"]
        if access_control and access_control.get(suite):
            hand["access_control_sinks"] = access_control[suite]
        with open(os.path.join(out_dir, f"{suite}.yaml"), "w") as f:
            f.write(f"# Generated by derive_grants.write_rule_configs — the sink taxonomy of\n"
                    f"# {suite}.yaml replaced by the rule (sinks = measured state changes;\n"
                    f"# egress iff a destination argument). Do not edit by hand.\n")
            yaml.safe_dump(hand, f, sort_keys=True)
