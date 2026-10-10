#!/usr/bin/env python3
"""Whose authority satisfies the consequence gate's "governance gate"?

`_check_consequence` (intent_loop.py:1320-1346) documents the exception it makes:
"The governance gate is satisfied by an active escalation grant or capability
lease for the tool (a human/operator-authorised path)." The test it performs is
`EscalationManager.covers(tool_name)` — presence of a grant, with no reference to
who approved it.

With `require_human=False` the grant is minted from the agent's own
`escalate_policy` intent and carries LeaseAuthorityType.AUTOMATED_POLICY
(escalation.py:222-247). So the "human/operator-authorised path" can be walked by
the model, and the sink the operator's ceiling was protecting executes.

The operator did set require_human=False, so this is not a bypass of their
configuration — it is two knobs of theirs contradicting each other
(`max_unattended_consequence` says this class needs a gate; `require_human=False`
says grants need no human) with the permissive one winning silently.
"""
from __future__ import annotations

import asyncio

from _corepath import RecordingHandler, envelope, say, tool_event

from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.node.intent_loop import IntentLoop

# `shutdown` is CATASTROPHIC by the built-in table (policy/consequence.py), i.e.
# above the default CONSEQUENTIAL ceiling: the one class gated out of the box.
SINK = "shutdown"


async def main() -> None:
    handler = RecordingHandler(SINK)
    cap = CapabilityExecutor()
    cap.register(handler)

    policy = ExecutionPolicy(
        name="auto-escalating",
        tool_policy=ToolPolicy(allow_read=True, extra_allowed=(SINK,)),
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=(SINK,),
            max_escalations=2, max_ops_per_grant=5,
            require_human=False,          # no approver configured, none consulted
        ),
    )
    env = envelope(policy)
    loop = IntentLoop(cap, [])            # escalation_callback=None

    before = await loop._resolve_tool_intent(tool_event(SINK, {}), env)
    granted = await loop._handle_escalation(
        tool_event("escalate_policy", {"tool": SINK, "reason": "ops", "max_ops": 1}), env)
    after = await loop._resolve_tool_intent(tool_event(SINK, {}), env)

    say("X1 an agent-issued, auto-approved grant lifts the CATASTROPHIC ceiling",
        (not before.approved) and granted.get("granted") is True
        and after.approved and bool(handler.log),
        f"before={before.approved} ({before.reason[:52]!r}) "
        f"grant={granted.get('granted')} after={after.approved} "
        f"handler_called={bool(handler.log)}")


asyncio.run(main())
