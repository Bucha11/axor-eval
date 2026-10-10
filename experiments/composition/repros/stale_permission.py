#!/usr/bin/env python3
"""Does a permission survive the loss of its basis — and do the live gates care?

The question is narrower than "is authority accumulating". A permanent overlay or
a standing clearance is not a defect by itself: it may be a deliberate change of
baseline. What is a defect is a permission surviving the loss of the condition it
was issued under.

The case that separates this from TTL and from one-shot use:

  1. a permission is issued in state s0;
  2. before dispatch, a condition essential to it changes;
  3. the TTL is still valid and the permission is unused;
  4. the same call is attempted.

One-shot use bounds the NUMBER of uses. It says nothing about whether the basis
of the FIRST use still holds.

Three columns, so "the basis-check adds nothing here" is visible wherever it is
true:

  axor   — the shipped kernel: an escalation grant with ops and a lease TTL;
  bound  — kernel AND a permission bound to the exact rendered call, single use
           (the contract of approval_series.py, no conditions);
  basis  — kernel AND the same binding AND the declared conditions
           (prototype/basis.py).

The sink is `bash`: CONSEQUENTIAL and so over a REVERSIBLE ceiling (the grant is
what admits it), with clean arguments and no egress, so neither the integrity
gate nor the confidentiality floor is what refuses it. That is on purpose — the
point is to find a basis loss the live gates do NOT compensate for.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))

from _corepath import RecordingHandler, envelope, say, tool_event

from basis import (Call, Permission, PermissionLedger, SessionState,
                   atomic_boundary, policy_version)

from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.degradation import DegradationLevel
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.contracts.trace import TraceEventKind
from axor_core.degradation.engine import DegradationEngine
from axor_core.node.intent_loop import IntentLoop

C = ConsequenceClass
SINK, ARGS, ESSENTIAL = "bash", {"command": "echo ok"}, ("command",)
CALL = Call(SINK, ARGS, ESSENTIAL).fingerprint()


async def _approve() -> bool:
    return True


def _policy(*, deny_bash: bool = False, grantable: tuple = (SINK,)) -> ExecutionPolicy:
    return ExecutionPolicy(
        name="p",
        tool_policy=ToolPolicy(allow_read=True, allow_bash=True,
                               extra_allowed=("fetch_page",),
                               extra_denied=(SINK,) if deny_bash else ()),
        max_unattended_consequence=C.REVERSIBLE,
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=grantable,
            max_escalations=2, max_ops_per_grant=5, require_human=True),
    )


def _untrusted_reads(events: list) -> int:
    return sum(1 for e in events
               if getattr(e, "kind", None) is TraceEventKind.TAINT_PROPAGATED)


async def scenario(name: str, *, change) -> dict:
    """Issue a grant, apply `change`, attempt the same call. Returns one row."""
    handler = RecordingHandler(SINK)
    cap = CapabilityExecutor()
    cap.register(handler)
    cap.register(RecordingHandler("fetch_page", "untrusted page text about things"))
    events: list = []

    engine = DegradationEngine()
    loop = IntentLoop(
        cap, events, degradation_engine=engine,
        untrusted_sources={"fetch_page"},
        consequence_overrides={"fetch_page": C.BENIGN},
        escalation_callback=lambda *a, **k: _approve(),
    )

    pol0 = _policy()
    env0 = envelope(pol0)
    state0 = SessionState(policy_version(pol0), int(engine.state.level),
                          _untrusted_reads(events))

    granted = await loop._handle_escalation(
        tool_event("escalate_policy", {"tool": SINK, "reason": "ops", "max_ops": 1}), env0)
    assert granted.get("granted") is True, granted

    ledger = PermissionLedger()
    ledger.issue(Permission(
        permission_id="p1", call=CALL, issuer="human_operator",
        expires_at=state0.policy_version and (9e18),   # TTL deliberately not the bound
        max_uses=1,
        at_policy_version=state0.policy_version,
        max_degradation=state0.degradation_level,
        at_untrusted_reads=state0.untrusted_reads,
    ), state0)

    # apply the change under test
    pol1 = await change(loop, engine, events, env0, pol0)
    env1 = envelope(pol1)
    state1 = SessionState(policy_version(pol1), int(engine.state.level),
                          _untrusted_reads(events))

    resolved = await loop._resolve_tool_intent(tool_event(SINK, ARGS), env1)
    kernel_ok = bool(resolved.approved)
    bound_ok, bound_why = ledger.decide(CALL, state1, conditions=False)
    basis_ok, basis_why = ledger.decide(CALL, state1, conditions=True)

    return dict(name=name, axor=kernel_ok, ran=bool(handler.log),
                bound=kernel_ok and bound_ok, basis=kernel_ok and basis_ok,
                why=basis_why if not basis_ok else bound_why,
                kernel_reason=resolved.reason)


# ── the changes under test ───────────────────────────────────────────────────

async def _nothing(loop, engine, events, env, pol):
    return pol

async def _operator_denies_the_tool(loop, engine, events, env, pol):
    """The operator explicitly denies the tool mid-session: an authority field
    changes, so the policy version changes."""
    return _policy(deny_bash=True)

async def _session_degrades(loop, engine, events, env, pol):
    engine._transition_to(DegradationLevel.LOCKED, source_id=None,
                          trigger_intent="t", reason="signals")
    return pol

async def _untrusted_read_happens(loop, engine, events, env, pol):
    await loop._resolve_tool_intent(tool_event("fetch_page", {"url": "http://x/y"}), env)
    return pol

async def _unrelated_event(loop, engine, events, env, pol):
    """A planning-only policy change: no authority field moves, no read, no
    degradation. The contract must let the permission stand."""
    import dataclasses
    from axor_core.contracts.policy import ContextMode
    return dataclasses.replace(pol, context_mode=ContextMode.BROAD)

async def _spend_it(loop, engine, events, env, pol):
    await loop._resolve_tool_intent(tool_event(SINK, ARGS), env)
    return pol


ROWS = [
    ("basis preserved",                      _nothing,                   True),
    ("operator denies the tool mid-session", _operator_denies_the_tool,  False),
    ("session degrades past the bound",      _session_degrades,          False),
    ("an untrusted read happens",            _untrusted_read_happens,    False),
    ("unrelated (planning-only) change",     _unrelated_event,           True),
    ("permission already spent",             _spend_it,                  False),
]


async def main() -> None:
    print(f"      {'scenario':38s} {'axor':>6s} {'bound':>6s} {'basis':>6s}  expected")
    rows = []
    for name, change, expected in ROWS:
        r = await scenario(name, change=change)
        rows.append((r, expected))
        print(f"      {name:38s} {str(r['axor']):>6s} {str(r['bound']):>6s} "
              f"{str(r['basis']):>6s}  {expected}")
        if not r["basis"] and r["why"]:
            print(f"        basis-check: {r['why'][:84]}")
        print(f"        kernel said: {r['kernel_reason'][:76]!r}")

    # Where does the basis check actually add anything? Only where the kernel and
    # the bound contract both admit and the basis says no.
    adds = [r["name"] for r, exp in rows if r["bound"] and not r["basis"]]
    compensated = [r["name"] for r, exp in rows if exp is False and not r["axor"]]
    say("S1 the basis check gives every row the expected verdict",
        all(r["basis"] is exp for r, exp in rows), "including the two rows that must stay admitted")
    say("S2 there is at least one basis loss the live gates do NOT compensate",
        bool(adds), f"basis check changes the outcome on: {adds or 'nothing'}")
    print(f"      already refused by the shipped gates (no new layer needed): {compensated}")
    print(f"      atomic boundary: {atomic_boundary()}")


asyncio.run(main())
