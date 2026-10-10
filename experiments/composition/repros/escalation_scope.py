#!/usr/bin/env python3
"""What does an escalation grant actually restore, and what survives it?

The docs present escalation as mid-execution CAPABILITY recovery — preset:readonly
says "agent may request write access mid-execution (e.g., found a bug while
reviewing and wants to apply a targeted fix)" (policy/presets.py) and carries
grantable_tools=("write",) with allow_write=False.

The grant is only stored if a CapabilityLease can be created for it
(escalation.py:241-256), and lease creation is bounded by the parent policy's
RESOLVED capability set (lease_validator.py:60-83, 124). That set comes from
tool_policy + extra_allowed only — resolver.py:68-86 never reads
escalation_policy.grantable_tools. So the two are checked against each other in a
way that makes the documented case impossible.

What the grant does do: satisfy the consequence gate's governance test
(`EscalationManager.covers`, escalation.py:92-98, read at intent_loop.py:1339).
That is one axis. The last check shows the floor is not that axis.
"""
from __future__ import annotations

import asyncio

from _corepath import RecordingHandler, envelope, say, tool_event

from axor_core.capability.executor import CapabilityExecutor
from axor_core.capability.lease_validator import LeaseValidator
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.lease import LeaseAuthorityType
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.node.intent_loop import IntentLoop
from axor_core.policy import presets

C = ConsequenceClass
EP = EscalationPolicy(allow_escalation=True, grantable_tools=("bash", "send_message"),
                      max_escalations=3, max_ops_per_grant=5, require_human=False)
GRANT = "escalate_policy"


def _cap() -> CapabilityExecutor:
    cap = CapabilityExecutor()
    cap.register(RecordingHandler("bash"))
    cap.register(RecordingHandler("read"))
    cap.register(RecordingHandler("send_message"))
    cap.register(RecordingHandler("read_secret", "SECRET_TOKEN_abcdef0123456789"))
    return cap


# ── E1: the lease ceiling, directly ──────────────────────────────────────────

_, err = LeaseValidator().create_lease(
    granted_by="operator", authority_type=LeaseAuthorityType.HUMAN_OPERATOR,
    allowed_tools=["write"], parent_policy=presets.readonly())
say("E1 a lease cannot name a tool the policy denies", err is not None,
    f"lease for 'write' against preset:readonly (whose own grantable_tools=('write',)) "
    f"-> err={err!r}")


async def main() -> None:
    # ── E2: the documented case, through the real grant path ─────────────────
    denied = ExecutionPolicy(name="no-bash", escalation_policy=EP,
                             tool_policy=ToolPolicy(allow_read=True, allow_bash=False))
    loop = IntentLoop(_cap(), [])
    result = await loop._handle_escalation(
        tool_event(GRANT, {"tool": "bash", "reason": "need it", "max_ops": 3}),
        envelope(denied))
    say("E2 escalation cannot restore a denied capability",
        result.get("granted") is not True, f"result={result}")

    # ── E3: what the grant does clear — the consequence ceiling ──────────────
    allowed = ExecutionPolicy(name="bash-ok", escalation_policy=EP,
                              max_unattended_consequence=C.REVERSIBLE,
                              tool_policy=ToolPolicy(allow_read=True, allow_bash=True))
    env = envelope(allowed)
    loop = IntentLoop(_cap(), [])
    before = await loop._resolve_tool_intent(tool_event("bash", {"command": "x"}), env)
    granted = await loop._handle_escalation(
        tool_event(GRANT, {"tool": "bash", "reason": "need it", "max_ops": 3}), env)
    after = await loop._resolve_tool_intent(tool_event("bash", {"command": "x"}), env)
    say("E3 the grant clears the consequence ceiling, and only a policy-allowed tool",
        (not before.approved) and granted.get("granted") is True and after.approved,
        f"before={before.approved} ({before.reason[:58]!r}) "
        f"grant={granted.get('granted')} after={after.approved}")

    # ── E4: the same grant against the confidentiality floor ─────────────────
    egress = ExecutionPolicy(
        name="egress", escalation_policy=EP, max_unattended_consequence=C.REVERSIBLE,
        tool_policy=ToolPolicy(allow_read=True,
                               extra_allowed=("send_message", "read_secret")))
    env2 = envelope(egress)
    loop2 = IntentLoop(_cap(), [], egress_sinks={"send_message"},
                       sensitive_sources={"read_secret"}, untrusted_sources=set(),
                       consequence_overrides={"read_secret": C.BENIGN})
    g2 = await loop2._handle_escalation(
        tool_event(GRANT, {"tool": "send_message", "reason": "need it", "max_ops": 3}), env2)
    send = {"text": "hi", "to": "a@b.c"}
    pre = await loop2._resolve_tool_intent(tool_event("send_message", send), env2)
    await loop2._resolve_tool_intent(tool_event("read_secret", {"path": ".env"}), env2)
    floor = loop2._taint_engine.confidentiality_floor_active()
    post = await loop2._resolve_tool_intent(tool_event("send_message", send), env2)
    say("E4 the grant does not clear the floor",
        g2.get("granted") is True and pre.approved and floor and not post.approved,
        f"grant={g2.get('granted')} egress_before_read={pre.approved} floor={floor} "
        f"egress_after_read={post.approved} ({post.reason[:60]!r})")


asyncio.run(main())
