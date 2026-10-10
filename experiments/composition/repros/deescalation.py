#!/usr/bin/env python3
"""Does authority come back after a recovery? Measured per basis.

Every published control in this space buys soundness by forbidding runtime change
to policy: Bounded Agents (2608.15888) — "narrowing is irreversible within a
session"; ScopeGate (2606.28679) — policy "must remain immutable for the
lifetime"; APPA (2607.24625) — labels "descend monotonically", and its own
limitations say revocation and expiry are not addressed. So the forward operation
is studied and the inverse is not.

This asks the inverse question of axor's four bases, which is the only place it
can be asked of four at once:

  1. is the widening BOUNDED at all (ops, TTL, one effect, or nothing)?
  2. when the bound is spent, does authority return to the BASELINE — not wider,
     and not narrower?
  3. is there a trace event when the widening ENDS?
  4. does the widening reset the evidence that would have re-narrowed?

Row 2 is the interesting one: "restored" means the decision after the recovery
equals the decision before it. Falling BELOW the baseline is as much a failure of
restoration as staying above it.
"""
from __future__ import annotations

import asyncio
import time

from _corepath import RecordingHandler, envelope, say, tool_event

from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.degradation import DegradationLevel, GovernanceAuthority
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.degradation.engine import DegradationEngine

C = ConsequenceClass
AUTHORITY = GovernanceAuthority(authority_id="ops", authority_type="human_operator",
                                reason_code="reviewed")


async def _approve() -> bool:
    return True


def _policy(**kw) -> ExecutionPolicy:
    base = dict(
        name="p", tool_policy=ToolPolicy(allow_read=True, allow_write=True, allow_bash=True),
        max_unattended_consequence=C.CONSEQUENTIAL,
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=("write", "bash"),
            max_escalations=3, max_ops_per_grant=5, require_human=True),
    )
    base.update(kw)
    return ExecutionPolicy(**base)


def _loop(**kw):
    from axor_core.node.intent_loop import IntentLoop
    cap = CapabilityExecutor()
    for name in ("write", "bash", "read"):
        cap.register(RecordingHandler(name))
    events: list = []
    return IntentLoop(cap, events, escalation_callback=lambda *a, **k: _approve(), **kw), events


# ── basis 1: escalation grant over a tool the policy ALREADY allows ──────────
# `write` is REVERSIBLE and sits inside the ceiling, so it needs no escalation.
# Escalating it anyway is the cleanest test of restoration: the baseline verdict
# is ALLOW, so anything other than ALLOW afterwards is a failure to restore.

async def grant_restoration() -> None:
    loop, _ev = _loop()
    env = envelope(_policy())
    args = {"path": "/tmp/x", "content": "y"}

    before = await loop._resolve_tool_intent(tool_event("write", args), env)
    g = await loop._handle_escalation(
        tool_event("escalate_policy", {"tool": "write", "reason": "fix", "max_ops": 1}), env)
    during = await loop._resolve_tool_intent(tool_event("write", args), env)
    after = await loop._resolve_tool_intent(tool_event("write", args), env)

    print(f"      baseline={before.approved} granted={g.get('granted')} "
          f"under-grant={during.approved} after-spent={after.approved}")
    print(f"      after-spent reason: {after.reason[:72]!r}")
    say("R1 a spent grant leaves the tool BELOW its baseline",
        before.approved and during.approved and not after.approved,
        "escalating a tool the policy already allowed, then spending the grant, "
        "loses the tool: `evaluate` denies on the exhausted lease "
        "(escalation.py:116-124) before the call can fall through to allowed_tools")

    end_events = [type(e).__name__ for e in _ev if "scalat" in type(e).__name__.lower()]
    say("R2 nothing in the trace marks the end of the widening",
        end_events == ["EscalationGrantedEvent"],
        f"escalation-related trace events over the whole sequence: {end_events}")


# ── basis 2: degradation clearance ──────────────────────────────────────────

def clearance_restoration() -> None:
    engine = DegradationEngine()
    engine.quarantine_source("web:evil", "injected instruction")
    quarantined_before = sum(1 for s in engine.state.sources.values() if s.quarantined)
    level_before = engine.state.level

    engine.clear_by_governance(AUTHORITY, "reviewed by oncall")
    quarantined_after = sum(1 for s in engine.state.sources.values() if s.quarantined)
    pressure = [(s.tool_pressure_count, s.instruction_pressure_count)
                for s in engine.state.sources.values()]

    print(f"      level {level_before.name} -> {engine.state.level.name}; "
          f"quarantined {quarantined_before} -> {quarantined_after}; "
          f"pressure counters now {pressure}; deny_count={engine.state.session_deny_count}")
    say("R3 a clearance is unbounded: no TTL, no use count, no expiry",
        not hasattr(engine, "_clearance_expires_at")
        and engine.state.level is DegradationLevel.NORMAL,
        "nothing in DegradationState carries a clearance lifetime — the session stays "
        "NORMAL until new signals arrive")
    say("R4 and it resets the evidence that would have re-narrowed quickly",
        quarantined_after == 0 and all(p == (0, 0) for p in pressure),
        "quarantine flags and both pressure counters are zeroed "
        "(engine.py:446-452), so each clearance hands back a full budget")
    say("R5 the clearance itself IS recorded",
        len(engine.state.level_history) >= 1
        and "governance_clearance" in engine.state.level_history[-1][2],
        f"level_history tail: {engine.state.level_history[-1][2]!r} — this is the one "
        "basis whose transition is in the record")


# ── bases 3 and 4: static by construction ───────────────────────────────────

def static_bases() -> None:
    pol = _policy(max_unattended_consequence=C.CATASTROPHIC)
    say("R6 a raised ceiling has no runtime end at all",
        pol.max_unattended_consequence is C.CATASTROPHIC,
        "the overlay/ceiling and the enum allowlist are policy fields: they hold for "
        "every call in the session, there is nothing to spend and nothing to withdraw")


async def main() -> None:
    await grant_restoration()
    clearance_restoration()
    static_bases()
    print()
    print("      basis            bounded?            restores to baseline?   end event?")
    print("      grant            ops + lease TTL     NO — falls below        no")
    print("      clearance        unbounded           n/a (no bound)          transition event")
    print("      ceiling/overlay  unbounded           n/a                     no")
    print("      enum allowlist   unbounded           n/a                     no")


asyncio.run(main())
