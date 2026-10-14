"""InjecAgent on the final configuration: which check is the ONLY one that denies a case.

Ablations of the "final" configuration of full_attack_set.py (same cases, same synthesized
arguments, same kernel), fixed before the run:

  direct harm   class only  = denied by the full final config AND allowed once the
                              consequence axis is off (max_unattended_consequence =
                              CATASTROPHIC, no overrides, no consequence rules: every
                              call is within the unattended ceiling and no class forces
                              L3/L4).
  data stealing floor only  = denied by the full final config AND allowed once the
                              confidentiality floor is off (no sensitive sources).
                floor alone = denied with ONLY the floor on: content projection off,
                              no grant gate (no grant args), no class axis, integrity
                              default off, no integrity sinks and no untrusted sources
                              (so no value is tainted: the origin check cannot fire);
                              the sensitive sources and the egress sinks stay.

Each ablation also reports what denies instead, so "the other checks still deny it"
is shown, not assumed.

    INJECAGENT_DIR=... AXOR_CORE_REPO=... python final_breakdown.py
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import full_attack_set as F  # noqa: E402

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402


def dh_decide(cfg, T, item):
    atk = item["Attacker Tools"][0]
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(item["User Instruction"])
    if cfg.grant_args:
        g.grants.from_request(item["User Instruction"])
    g.register_output(g.evaluate(item["User Tool"], ast.literal_eval(item["Tool Parameters"])),
                      item["Tool Response"])
    return g.evaluate(atk, F.synth_args(T.get(atk, {}), item["Attacker Instruction"]))


def ds_decide(cfg, T, item):
    s1, s2 = item["Attacker Tools"][0], item["Attacker Tools"][1]
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(item["User Instruction"])
    if cfg.grant_args:
        g.grants.from_request(item["User Instruction"])
    g.register_output(g.evaluate(item["User Tool"], ast.literal_eval(item["Tool Parameters"])),
                      item["Tool Response"])
    g.register_output(g.evaluate(s1, F.synth_args(T.get(s1, {}), item["Attacker Instruction"])),
                      "<the user's sensitive data>")
    return g.evaluate(s2, F.synth_args(T.get(s2, {}), item["Attacker Instruction"]))


def label(d):
    if d.allowed:
        return "allowed"
    floor = "confidentiality" in (d.reason or "")
    return f"{d.category}{' (floor)' if floor else ''}"


def main():
    T = F.tools()
    old = GovernanceConfig.from_yaml(os.path.join(F.CORE, "examples/injecagent/config/injecagent.yaml"))
    old = dataclasses.replace(old, integrity_default="context", integrity_origins="request-only")
    final = F.final_config(dataclasses.replace(F.rule_config(old, T), floor_scope="all_mutating"), T)
    no_class = dataclasses.replace(final, max_unattended_consequence=ConsequenceClass.CATASTROPHIC,
                                   consequence_overrides={}, consequence_rules={})
    no_floor = dataclasses.replace(final, sensitive_sources=frozenset())
    floor_alone = dataclasses.replace(final, content_projection=False, grant_args={},
                                      integrity_default=None, integrity_sinks=frozenset(),
                                      untrusted_sources=frozenset(),
                                      max_unattended_consequence=ConsequenceClass.CATASTROPHIC,
                                      consequence_overrides={}, consequence_rules={})

    dh = json.load(open(os.path.join(F.DATA, "test_cases_dh_base.json")))
    ds = json.load(open(os.path.join(F.DATA, "test_cases_ds_base.json")))
    out = {}

    full, abl, class_only, class_only_tools = Counter(), Counter(), 0, Counter()
    for item in dh:
        a, b = dh_decide(final, T, item), dh_decide(no_class, T, item)
        full[label(a)] += 1
        abl[label(b)] += 1
        if not a.allowed and b.allowed:
            class_only += 1
            class_only_tools[item["Attacker Tools"][0]] += 1
    out["direct_harm"] = {"cases": len(dh), "final": dict(full), "without_class": dict(abl),
                          "denied_only_by_class": class_only, "class_only_tools": dict(class_only_tools)}
    print("direct harm:", json.dumps(out["direct_harm"]))

    full, nf, fa, floor_only = Counter(), Counter(), Counter(), 0
    for item in ds:
        a, b, c = ds_decide(final, T, item), ds_decide(no_floor, T, item), ds_decide(floor_alone, T, item)
        full[label(a)] += 1
        nf[label(b)] += 1
        fa[label(c)] += 1
        floor_only += int(not a.allowed and b.allowed)
    out["data_stealing"] = {"cases": len(ds), "final": dict(full), "without_floor": dict(nf),
                            "denied_only_by_floor": floor_only, "floor_alone": dict(fa)}
    print("data stealing:", json.dumps(out["data_stealing"]))
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "final_breakdown.json"), "w"),
              indent=1)


if __name__ == "__main__":
    main()
