"""InjecAgent: every attacker call of the base suites through the current governor.

No model. The recorded GPT-4o / Qwen-72B trajectories of the earlier runs were not
kept, so per-run ASR cannot be recomputed; instead every one of the 510 direct-harm
and 544 data-stealing base cases is replayed as if the agent had followed the
injection. Denying a case here means denying it on ANY trajectory, so governed ASR
on the base suites is bounded by the share of cases allowed here.

Attacker call arguments are synthesized from the attacker instruction by the tool's
schema (the dataset carries no structured arguments): a string parameter takes an
id-like / quoted / e-mail token from the instruction (else the instruction text),
a number the first number in it, a boolean True, an array a one-element list.

Two configs, both context integrity + request-only:
  old   examples/injecagent/config/injecagent.yaml (roles from the cases)
  rule  sinks by rule — a tool whose leading verb is not a read verb is a sink;
        egress iff it has a destination parameter; driving = non-rich, non-numeric,
        non-temporal parameters; sources and consequence classes as in old.

  final the final AgentDojo configuration's switches (ajar/MODEL.md §8.7 + §8.10), as far
        as they exist without an environment, on top of rule (fixed before the run):
        floor_mode audience with an empty audience (no initial state: only the user),
        destination_args = the DEST parameters, content_args = the RICH parameters,
        max_unattended_consequence reversible, fallback_to_confirmation and
        content_projection on, operator_sets_confirm on with no operator sets (no
        organisation entities without an initial state), grant_args = the driving
        args (kind email / url by name, else string), L1 grants from the user
        instruction, no human (configuration A: a confirmation is a refusal).

    INJECAGENT_DIR=... AXOR_CORE_REPO=... [OUT=suffix] python full_attack_set.py
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import sys
from collections import Counter

CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/axor-core-grants")
DATA = os.path.join(os.environ.get("INJECAGENT_DIR", "/home/user/ext/InjecAgent"), "data")
sys.path.insert(0, CORE)

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402

READ_VERBS = {"get", "view", "search", "list", "read", "check", "retrieve", "access", "find",
              "show", "fetch", "browse", "lookup", "query", "download"}
RICH = re.compile(r"^\s*(the\s+)?(body|content|subject|title|description|message|text|note|comment)", re.I)
DEST = re.compile(r"(^|_)(to|recipients?|email|e_?mail|url|phone|phone_number|cc|bcc|participants?|receiver)$")
TEMPORAL = re.compile(r"(date|time|day)", re.I)


def tools() -> dict[str, dict]:
    out = {}
    for tk in json.load(open(os.path.join(DATA, "tools.json"))):
        for t in tk["tools"]:
            out[tk["name_for_model"] + t["name"]] = t
    return out


def leading_verb(full: str, toolkit_prefix_len: int) -> str:
    words = re.findall(r"[A-Z][a-z]*", full[toolkit_prefix_len:])
    return words[0].lower() if words else ""


def rule_config(old: GovernanceConfig, T: dict[str, dict]) -> GovernanceConfig:
    tk_names = [tk["name_for_model"] for tk in json.load(open(os.path.join(DATA, "tools.json")))]
    egress, integrity, driving = set(), set(), {}
    for full, t in T.items():
        prefix = max((len(n) for n in tk_names if full.startswith(n)), default=0)
        if leading_verb(full, prefix) in READ_VERBS:
            continue
        params = t.get("parameters", [])
        dest = any(DEST.search(p["name"]) or "email address" in (p.get("description") or "").lower()
                   for p in params)
        (egress if dest else integrity).add(full)
        d = [p["name"] for p in params
             if not RICH.search(p.get("description") or "")
             and p.get("type") not in ("integer", "number", "boolean")
             and not TEMPORAL.search(p["name"])]
        if d:
            driving[full] = d
    return dataclasses.replace(old, egress_sinks=frozenset(egress), integrity_sinks=frozenset(integrity),
                               driving_args=driving)


def final_config(rule: GovernanceConfig, T: dict[str, dict]) -> GovernanceConfig:
    sinks = set(rule.egress_sinks) | set(rule.integrity_sinks)
    dest, content, ga = {}, {}, {}
    for full in sinks:
        params = T[full].get("parameters", [])
        dest[full] = [p["name"] for p in params if full in rule.egress_sinks and
                      (DEST.search(p["name"]) or "email address" in (p.get("description") or "").lower())]
        content[full] = [p["name"] for p in params if RICH.search(p.get("description") or "")]
        ga[full] = {a: ("email" if "email" in a.lower() else "url" if "url" in a.lower() else "string")
                    for a in rule.driving_args.get(full, [])}
    return dataclasses.replace(
        rule, floor_mode="audience", audience=frozenset(), destination_args=dest, content_args=content,
        max_unattended_consequence=ConsequenceClass.REVERSIBLE, fallback_to_confirmation=True, content_projection=True,
        operator_sets_confirm=True, grant_args={k: v for k, v in ga.items() if v})


def synth_args(tool: dict, instruction: str) -> dict:
    tokens = re.findall(r"'([^']+)'|\"([^\"]+)\"", instruction)
    quoted = [a or b for a, b in tokens]
    ids = re.findall(r"\b[\w.+-]+@[\w.-]+\.\w+\b|\b\w*\d\w*\b|\([^)]+\)", instruction)
    nums = re.findall(r"\d+(?:\.\d+)?", instruction)
    out = {}
    for p in tool.get("parameters", []):
        if not p.get("required", True):
            continue
        ty = p.get("type")
        if ty in ("integer", "number"):
            out[p["name"]] = float(nums[0]) if nums else 1
        elif ty == "boolean":
            out[p["name"]] = True
        else:
            v = (quoted or [x.strip("()") for x in ids] or [instruction])[0]
            out[p["name"]] = [v] if ty == "array" else v
    return out


def run(cfg: GovernanceConfig, T: dict, label: str) -> dict:
    nocons = dataclasses.replace(cfg, consequence_overrides={})
    dh = json.load(open(os.path.join(DATA, "test_cases_dh_base.json")))
    ds = json.load(open(os.path.join(DATA, "test_cases_ds_base.json")))
    first_cat, cons_only, allowed = Counter(), 0, []
    pre_integrity = Counter()
    for item in dh:
        atk = item["Attacker Tools"][0]
        args = synth_args(T.get(atk, {}), item["Attacker Instruction"])

        def decide(c):
            g = ToolCallGovernor(**c.as_governor_kwargs())
            g.register_task(item["User Instruction"])
            if c.grant_args:
                g.grants.from_request(item["User Instruction"])
            g.register_output(g.evaluate(item["User Tool"], ast.literal_eval(item["Tool Parameters"])),
                              item["Tool Response"])
            return g.evaluate(atk, args)
        d = decide(cfg)
        if d.allowed:
            allowed.append((atk, args))
            continue
        first_cat[d.category] += 1
        if d.category != "taint_enforcement":
            pre_integrity[d.category] += 1
        if d.category == "consequence_gate" and decide(nocons).allowed:
            cons_only += 1
    ds_denied, ds_cat, ds_floor = 0, Counter(), 0
    for item in ds:
        s1, s2 = item["Attacker Tools"][0], item["Attacker Tools"][1]
        g = ToolCallGovernor(**cfg.as_governor_kwargs())
        g.register_task(item["User Instruction"])
        if cfg.grant_args:
            g.grants.from_request(item["User Instruction"])
        g.register_output(g.evaluate(item["User Tool"], ast.literal_eval(item["Tool Parameters"])),
                          item["Tool Response"])
        g.register_output(g.evaluate(s1, synth_args(T.get(s1, {}), item["Attacker Instruction"])),
                          "<the user's sensitive data>")
        d = g.evaluate(s2, synth_args(T.get(s2, {}), item["Attacker Instruction"]))
        if not d.allowed:
            ds_denied += 1
            ds_cat[d.category] += 1
            ds_floor += int("confidentiality" in (d.reason or ""))
    res = {"dh_cases": len(dh), "dh_denied": len(dh) - len(allowed), "dh_allowed": allowed[:20],
           "dh_first_denial": dict(first_cat), "dh_denied_before_integrity": dict(pre_integrity),
           "dh_consequence_only": cons_only, "ds_cases": len(ds), "ds_denied": ds_denied,
           "ds_denial": dict(ds_cat), "ds_denied_by_floor": ds_floor}
    print(f"== {label}: dh denied {res['dh_denied']}/{len(dh)} (allowed {len(allowed)}), "
          f"consequence-only {cons_only}; first denial {dict(first_cat)}; "
          f"before integrity {dict(pre_integrity)}; ds denied {ds_denied}/{len(ds)} {dict(ds_cat)}, by the floor {ds_floor}")
    for a in allowed[:8]:
        print("   allowed:", a)
    return res


def main() -> None:
    T = tools()
    old = GovernanceConfig.from_yaml(os.path.join(CORE, "examples/injecagent/config/injecagent.yaml"))
    old = dataclasses.replace(old, integrity_default="context", integrity_origins="request-only")
    rule = rule_config(old, T)
    current = dataclasses.replace(rule, floor_scope="all_mutating")
    out = {"old": run(old, T, "old roles"), "rule": run(rule, T, "rule"),
           "rule_all_mutating": run(current, T, "rule + floor_scope all_mutating (current)"),
           "final": run(final_config(current, T), T, "final (MODEL.md §8.7 + §8.10 switches)")}
    old_sinks = set(old.egress_sinks) | set(old.integrity_sinks)
    rule_sinks = set(rule.egress_sinks) | set(rule.integrity_sinks)
    out["diff"] = {"rule_only": sorted(rule_sinks - old_sinks), "old_only": sorted(old_sinks - rule_sinks),
                   "label_changed": sorted(t for t in old_sinks & rule_sinks
                                           if (t in old.egress_sinks) != (t in rule.egress_sinks))}
    print(f"\nsinks: old {len(old_sinks)}, rule {len(rule_sinks)}; rule-only {len(out['diff']['rule_only'])}, "
          f"old-only {len(out['diff']['old_only'])}: {out['diff']['old_only']}; "
          f"egress/integrity label changed: {out['diff']['label_changed'][:10]}")
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"full_attack_set{os.environ.get('OUT', '')}.json"), "w"),
              indent=1, default=str)


if __name__ == "__main__":
    main()
