#!/usr/bin/env python3
"""The missing intersection, executed rather than read.

A parent whose operator lowered the unattended consequence ceiling to REVERSIBLE
cannot run `bash` (CONSEQUENTIAL) without a governance gate. It spawns a child.
The child's policy is selected fresh by the child node (wrapper.py:640-644 passes
no override_policy, so TaskAnalyzer + PolicySelector choose it) and no preset sets
`max_unattended_consequence`, so the child sits at the CONSEQUENTIAL default —
which `apply_parent_restrictions` does not pull back down.

The check is on the handler, not on a verdict: did bash actually execute?
"""
from __future__ import annotations

import asyncio

from _corepath import RecordingHandler, ScriptedAgent, say

from axor_core import GovernedSession
from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.policy import (
    ChildMode, CompressionMode, ContextMode, ExecutionPolicy, ExportMode, ToolPolicy,
)
from axor_core.contracts.trace import TraceConfig

# A task string the stock analyzer classifies as focused_mutative — the point is
# only that the child's preset grants bash, not how the classifier got there.
CHILD_TASK = "run the test suite and fix the failing build"


async def main() -> None:
    executed: list = []
    cap = CapabilityExecutor()
    cap.register(RecordingHandler("bash", log=executed))

    seen: list[str] = []

    def _note(envelope) -> None:
        seen.append(f"{envelope.policy.name} "
                    f"ceiling={envelope.policy.max_unattended_consequence.name}")

    session = GovernedSession(
        executor=ScriptedAgent([("bash", {"command": "echo PARENT"}),
                                ("spawn_child", {"task": CHILD_TASK})]),
        child_executor=ScriptedAgent([("bash", {"command": "echo CHILD"})],
                                     on_envelope=_note),
        capability_executor=cap,
        trace_config=TraceConfig(local_only=True, persist_inputs=False),
    )

    operator_policy = ExecutionPolicy(
        name="operator:reversible-ceiling",
        max_unattended_consequence=ConsequenceClass.REVERSIBLE,
        context_mode=ContextMode.MODERATE, compression_mode=CompressionMode.BALANCED,
        child_mode=ChildMode.ALLOWED, max_child_depth=2,
        tool_policy=ToolPolicy(allow_read=True, allow_write=True, allow_bash=True,
                               allow_search=True, allow_spawn=True),
        export_mode=ExportMode.SUMMARY, child_context_fraction=0.5,
    )
    await session.run("run everything and delegate", policy=operator_policy)

    commands = [args.get("command") for _, args in executed]
    parent_ran = "echo PARENT" in commands
    child_ran = "echo CHILD" in commands
    print(f"      parent policy ceiling=REVERSIBLE; child envelope: {seen or ['(no child)']}")
    say("S1 a spawned child executes the sink its parent is forbidden to execute",
        (not parent_ran) and child_ran,
        f"bash handler invoked with {commands}; parent_ran={parent_ran} child_ran={child_ran}")


asyncio.run(main())
