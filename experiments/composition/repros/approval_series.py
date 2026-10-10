#!/usr/bin/env python3
"""One series on F10, done properly: what the approval authorises vs what executes.

The matrix in `basis_pairs.py` was mis-stated. It does NOT violate
`W(a∘b) ⊆ W(a) ∪ W(b)`: with W(enum)={integrity} and W(grant)={consequence},
exactly those two obligations were lifted and nothing escaped the union. It shows
that rule is **insufficient**, not broken — and likewise that disjoint scopes buy
the absence of certain interactions, never the safety of the jointly admitted
effect.

The real statement. axor's consequence obligation is defined over EFFECTS (a
ceiling on how irreversible one call may be unattended). The basis that lifts it
asks the approver about a TOOL: `(tool_use_id, tool, paths, max_ops)`
(`escalation.py:226-228`). For a sink whose effect is determined by a non-path
parameter, the approval cannot express the effect, and a second basis fills the
missing parameters in. That is a missing contract, not an approval bypass — if
the interface promises tool-wide permission, the admitted effect is the price of
broad delegation.

So the series below holds the sink fixed and varies only what the approver saw
versus what the run drives. Two columns: the kernel as it ships, and the
prototype contract (`prototype/approval.py`) where the obligation is replaced
rather than removed:

    admits_consequence(e) ⟺ class(e) ≤ ceiling ∨ valid_approval(a, e, now)

`send_money` is the sink: `recipient` is the declared driving arg an enum covers,
`amount` is essential to the effect and is NOT a driving arg — so supersession
fires on the declaration while the amount rides along unconstrained.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))

from _corepath import RecordingHandler, envelope, say, tool_event

from approval import (Approval, ApprovalLedger, Effect, admits_consequence,
                      execute_bound)

from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.degradation import DegradationLevel, GovernanceAuthority
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.contracts.taint import TaintSource
from axor_core.degradation.engine import DegradationEngine
from axor_core.node.intent_loop import IntentLoop
from axor_core.policy.value_policy import ValuePredicate
from axor_core.taint.causal_root import CausalRoot

C = ConsequenceClass
SINK = "send_money"
ESSENTIAL = ("recipient", "amount")

PAYEE_A = "GB29NWBK60161331926819"      # the one the approver saw
PAYEE_B = "US122000000121212121212"     # another member of the same operator enum
APPROVED_ENUM = frozenset({PAYEE_A, PAYEE_B})
AMOUNT_SEEN = 200
AMOUNT_OTHER = 5000

AUTHORITY = GovernanceAuthority(authority_id="ops", authority_type="human_operator",
                                reason_code="reviewed")


async def _approve() -> bool:
    return True


# ── column 1: the kernel as it ships ─────────────────────────────────────────

async def kernel(args: dict, *, ops: int = 1, expire: bool = False,
                 second_call: bool = False, cleared: bool = False) -> bool:
    handler = RecordingHandler(SINK)
    cap = CapabilityExecutor()
    cap.register(handler)

    engine = None
    if cleared:
        engine = DegradationEngine()
        engine._transition_to(DegradationLevel.LOCKED, source_id=None,
                              trigger_intent="t", reason="repro")
        engine.clear_by_governance(AUTHORITY, "reviewed")

    loop = IntentLoop(
        cap, [],
        value_policies={SINK: [ValuePredicate(arg="recipient", kind="enum",
                                              allowed=APPROVED_ENUM)]},
        driving_args={SINK: ["recipient"]},     # amount is not declared driving
        integrity_sinks={SINK},
        degradation_engine=engine,
        escalation_callback=lambda *a, **k: _approve(),
    )
    # the recipient arrives from an untrusted read: the run chooses it
    loop._taint_engine.register_value(args["recipient"],
                                      CausalRoot.external_read(TaintSource.WEB))

    policy = ExecutionPolicy(
        name="p", tool_policy=ToolPolicy(allow_read=True, extra_allowed=(SINK,)),
        max_unattended_consequence=C.REVERSIBLE,
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=(SINK,), max_escalations=2,
            max_ops_per_grant=5, require_human=True),
    )
    env = envelope(policy)
    # The approver is asked about the TOOL (and paths, and an op count) — never
    # about recipient or amount.
    g = await loop._handle_escalation(
        tool_event("escalate_policy", {"tool": SINK, "reason": "payroll", "max_ops": ops}), env)
    assert g.get("granted") is True, g

    if expire:
        # Age the lease past its TTL rather than waiting 300s for it.
        lease = loop._escalation._capability_leases[SINK]
        object.__setattr__(lease, "expiration_time", time.time() - 1)
        assert lease.expiration_time < time.time()
    if second_call:
        await loop._resolve_tool_intent(tool_event(SINK, args), env)

    r = await loop._resolve_tool_intent(tool_event(SINK, args), env)
    return bool(r.approved)


# ── column 2: the prototype contract ─────────────────────────────────────────

def _ledger(max_uses: int = 1, ttl: float = 60.0) -> ApprovalLedger:
    led = ApprovalLedger()
    led.issue(Approval(
        approval_id="ap-1", sink=SINK,
        bound={"recipient": PAYEE_A, "amount": AMOUNT_SEEN},   # what the approver saw
        issuer="human_operator", expires_at=time.time() + ttl, max_uses=max_uses,
    ))
    return led


def contract(args: dict, *, max_uses: int = 1, ttl: float = 60.0,
             consume_first: bool = False) -> tuple[bool, str]:
    led = _ledger(max_uses=max_uses, ttl=ttl)
    effect = Effect(SINK, args, ESSENTIAL)
    if consume_first:
        ok, which = led.valid_approval(effect)
        if ok:
            led.consume(which, effect)
    return admits_consequence(effect, C.REVERSIBLE, led)


ROWS = [
    ("approved call, unchanged",
     dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), {}, {}, True),
    ("destination swapped for another member of the same enum",
     dict(recipient=PAYEE_B, amount=AMOUNT_SEEN), {}, {}, False),
    ("another essential parameter changed (amount)",
     dict(recipient=PAYEE_A, amount=AMOUNT_OTHER), {}, {}, False),
    ("replayed after the permission is used up",
     dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), dict(second_call=True), dict(consume_first=True), False),
    ("used after expiry",
     dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), dict(expire=True), dict(ttl=-1.0), False),
    ("swapped destination, then a second recovery basis (clearance) added",
     dict(recipient=PAYEE_B, amount=AMOUNT_SEEN), dict(cleared=True), {}, False),
]


async def main() -> None:
    print(f"      {'check':58s} {'kernel':>8s} {'contract':>9s}  expected")
    kernel_gap, contract_ok = [], True
    for label, args, kw_kernel, kw_contract, expected in ROWS:
        k = await kernel(args, **kw_kernel)
        c, why = contract(args, **kw_contract)
        print(f"      {label:58s} {str(k):>8s} {str(c):>9s}  {expected}")
        if c is not expected:
            contract_ok = False
            print(f"        contract said: {why}")
        if k is not expected:
            kernel_gap.append(label)

    say("V1 the shipped kernel admits the rows where the effect was never approved",
        kernel_gap == [ROWS[1][0], ROWS[2][0], ROWS[5][0]],
        f"kernel diverges from the expectation on: {kernel_gap}")
    say("V2 the effect-level contract gives every row the expected verdict",
        contract_ok, "including admitting row 1 — the recovery it protects still works")

    # The binding has to reach the handler, not stop at the check.
    approved = Effect(SINK, dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), ESSENTIAL)
    ok_same, _ = execute_bound(approved, approved.fingerprint(),
                               dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), ESSENTIAL)
    ok_mut, why_mut = execute_bound(approved, approved.fingerprint(),
                                    dict(recipient=PAYEE_B, amount=AMOUNT_SEEN), ESSENTIAL)
    say("V3 a mutation between the check and the call is refused",
        ok_same and not ok_mut, f"unchanged={ok_same}, mutated={ok_mut} ({why_mut})")

    # What the trace can show today, which is what a replay has to work from.
    led = _ledger()
    eff = Effect(SINK, dict(recipient=PAYEE_A, amount=AMOUNT_SEEN), ESSENTIAL)
    ok, which = led.valid_approval(eff)
    led.consume(which, eff)
    led.revoke(which)
    kinds = [e[0] for e in led.events]
    say("V4 the ledger records the lifecycle a replay needs",
        kinds == ["issued", "used", "revoked"],
        f"prototype events={kinds}; axor today emits only ESCALATION_GRANTED/DENIED "
        "(contracts/trace.py:49-50) — commit() decrements with no event and an expired "
        "lease is deleted with no event (escalation.py:72-78, 116-124)")


asyncio.run(main())
