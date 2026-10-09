#!/usr/bin/env python3
"""Mechanical half of the premise audit: does the taxonomy match the suite?

Phase 0b asks whether the paper's premises hold on the deployments we measure.
Three of its questions are decidable by reading the suite's own tool schemas
against the operator's YAML, with no model and no judgement, so they belong in a
script that runs in CI rather than in a table somebody maintains by hand:

1. **Every declared tool exists.** A role declared for a tool the suite does not
   have is silently inert: `egress_sinks: [send_mail]` against a suite whose tool
   is `send_email` declares nothing at all, and the floor then never fires on the
   sink the operator thought they had covered.
2. **Every driving arg exists on its tool.** `driving_args` names the field the
   taint decision narrows to. A name that is not in the tool's schema narrows the
   check to nothing present, and `driving_subset` falls back to a subset that
   cannot contain the destination — the gate stops seeing the recipient.
3. **No driving arg has a non-None default** (P6, executed == checked). AgentDojo's
   `run_function` validates arguments through the tool's pydantic model before
   calling it, so a defaulted field can appear in the executed call having never
   been in the checked one. For a *driving* arg that means an unchecked
   destination. A `None` default cannot name a destination and is accepted; any
   other default is a finding.

What this cannot decide stays in the manual part of Phase 0b: whether a read's
source is third-party writable (P3), whether an undeclared write is externally
visible (P4), and the write→read graph behind trusted inputs (P6).

    python analysis/check_taxonomy_against_suite.py [--suite workspace] ...

Exit status is 1 if any finding is reported.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "agentdojo"))

from axor_core.config import GovernanceConfig  # noqa: E402

_CORE = pathlib.Path(
    os.environ.get("AXOR_CORE_REPO")
    or pathlib.Path(__file__).resolve().parents[4] / "axor-core"
)
_CONFIG_DIR = _CORE / "examples" / "agentdojo" / "config"

ROLE_FIELDS = (
    "untrusted_sources", "sensitive_sources", "egress_sinks",
    "imperative_sinks", "positional_sinks", "integrity_sinks", "benign_tools",
)


def suite_tools(suite_name: str) -> dict[str, object]:
    from agentdojo.task_suite.load_suites import get_suites

    return {t.name: t for t in get_suites("v1")[suite_name].tools}


def check(suite_name: str, config_path: pathlib.Path) -> list[str]:
    cfg = GovernanceConfig.from_yaml(str(config_path))
    tools = suite_tools(suite_name)
    findings: list[str] = []

    # 1. declared tools exist
    for field in ROLE_FIELDS:
        for name in sorted(getattr(cfg, field) or ()):
            if name not in tools:
                findings.append(
                    f"{suite_name}: {field} names '{name}', which is not a tool of "
                    f"this suite — the role is inert"
                )
    for name in sorted(cfg.consequence_overrides or {}):
        if name not in tools:
            findings.append(
                f"{suite_name}: consequence_overrides names '{name}', not a tool of "
                f"this suite — the override is inert"
            )

    # 2 and 3. driving args exist, and carry no payload-bearing default
    for tool_name, args in sorted((cfg.driving_args or {}).items()):
        tool = tools.get(tool_name)
        if tool is None:
            findings.append(
                f"{suite_name}: driving_args names '{tool_name}', not a tool of this "
                f"suite — the narrowing is inert"
            )
            continue
        fields = tool.parameters.model_fields  # type: ignore[attr-defined]
        for arg in args:
            field = fields.get(arg)
            if field is None:
                findings.append(
                    f"{suite_name}: driving_args['{tool_name}'] names '{arg}', which "
                    f"is not an argument of that tool (has: {sorted(fields)}) — the "
                    f"taint check narrows to nothing"
                )
                continue
            if field.is_required():
                continue
            default = field.get_default(call_default_factory=True)
            if default is not None:
                findings.append(
                    f"{suite_name}: driving arg '{tool_name}.{arg}' defaults to "
                    f"{default!r} — a defaulted driving arg can reach the handler "
                    f"without having been checked (P6)"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", action="append", dest="suites",
        help="suite name; repeatable. Default: every <suite>.yaml in the config dir",
    )
    args = parser.parse_args(argv)
    suites = args.suites or ["banking", "slack", "travel", "workspace"]

    all_findings: list[str] = []
    for suite_name in suites:
        path = _CONFIG_DIR / f"{suite_name}.yaml"
        if not path.exists():
            print(f"{suite_name}: no config at {path}, skipped")
            continue
        findings = check(suite_name, path)
        status = "ok" if not findings else f"{len(findings)} finding(s)"
        print(f"{suite_name}: {status}")
        for f in findings:
            print(f"  - {f}")
        all_findings += findings

    print(f"\n{len(all_findings)} finding(s) total")
    return 1 if all_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
