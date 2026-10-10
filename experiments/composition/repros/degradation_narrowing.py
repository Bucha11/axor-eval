#!/usr/bin/env python3
"""Is `DegradationEngine.apply_to_policy` the narrowing its contract claims?

Its docstring says "Return a narrowed ExecutionPolicy for the current degradation
state" (degradation/engine.py:327-334). At LOCKED/TERMINAL it builds a fresh
ToolPolicy with allow_read=True and the escalate tools in extra_allowed
(engine.py:372-390), ignoring what the base policy granted — so for a policy that
forbids reading, the "narrowed" policy is wider than the input.

The last two checks are the reason this is a latent contract break and not a live
hole: the only call site keeps the result local (intent_loop.py:1418), its LOCKED
branch never reads it, and the capability gate still runs against the envelope's
own capabilities.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from _corepath import RecordingHandler, envelope, say, tool_event

from axor_core.capability.executor import CapabilityExecutor
from axor_core.capability.resolver import CapabilityResolver
from axor_core.contracts.degradation import DegradationLevel
from axor_core.contracts.policy import ExecutionPolicy, ToolPolicy
from axor_core.degradation.engine import DegradationEngine
from axor_core.node.intent_loop import IntentLoop

CORE = Path(__file__).resolve().parents[4] / "axor-core"

NO_READ = ExecutionPolicy(
    name="no-read",
    tool_policy=ToolPolicy(allow_read=False, allow_write=False, allow_bash=False,
                           allow_search=False, allow_spawn=False),
)


def _locked() -> DegradationEngine:
    engine = DegradationEngine()
    engine._transition_to(DegradationLevel.LOCKED, source_id=None,
                          trigger_intent="t", reason="repro")
    return engine


locked = _locked().apply_to_policy(NO_READ, source_id=None)

say("G1 LOCKED turns allow_read on",
    NO_READ.tool_policy.allow_read is False and locked.tool_policy.allow_read is True,
    f"base allow_read={NO_READ.tool_policy.allow_read} -> "
    f"locked allow_read={locked.tool_policy.allow_read}")

added_names = set(locked.tool_policy.extra_allowed) - set(NO_READ.tool_policy.extra_allowed)
say("G2 LOCKED adds tool names the base never granted", bool(added_names),
    f"base extra={NO_READ.tool_policy.extra_allowed} -> locked extra={locked.tool_policy.extra_allowed}")

base_caps = CapabilityResolver().resolve(NO_READ).allowed_tools
locked_caps = CapabilityResolver().resolve(locked).allowed_tools
say("G3 the resolved capability set is not a subset of the input's",
    not (locked_caps <= base_caps),
    f"base={sorted(base_caps)} locked={sorted(locked_caps)} added={sorted(locked_caps - base_caps)}")

# ── scope: who consumes the returned policy ──────────────────────────────────

loop_src = (CORE / "axor_core" / "node" / "intent_loop.py").read_text()
call_sites = [m for m in re.findall(r"^.*apply_to_policy\(.*$", loop_src, re.M)]
block = loop_src[loop_src.index("def _check_degradation_denial"):]
block = block[:block.index("# ── Helpers")]
locked_branch = block[block.index("if level >= DegradationLevel.LOCKED"):
                      block.index("elif level == DegradationLevel.RESTRICTED")]
say("G4 one call site, and the LOCKED branch never reads the result",
    len(call_sites) == 1 and "effective" not in locked_branch,
    f"call sites={len(call_sites)}; LOCKED branch tests the tool name against "
    "_LOCKED_ALLOWED_TOOLS only")


async def main() -> None:
    read = RecordingHandler("read", "content")
    cap = CapabilityExecutor()
    cap.register(read)
    loop = IntentLoop(cap, [], degradation_engine=_locked())
    resolved = await loop._resolve_tool_intent(
        tool_event("read", {"path": "a.txt"}), envelope(NO_READ))
    say("G5 so the widening is inert end to end",
        (not resolved.approved) and not read.log,
        f"read approved={resolved.approved} handler_called={bool(read.log)} "
        f"({resolved.reason[:58]!r})")


asyncio.run(main())
