#!/usr/bin/env python3
"""Do two widening bases compose into a lift neither one authorises?

The two bases axor ships that actually fire:

  * `enum`-supersession lifts the INTEGRITY obligation on a sink whose driving
    args are all covered by an operator-declared enum. Its soundness argument is
    "the attacker can only ever choose a value the operator approved"
    (gates.py:196-204).
  * an escalation grant lifts the CONSEQUENCE ceiling for a tool (covers() read
    at intent_loop.py:1339), on the premise that a human/operator authorised the
    over-ceiling action.

Each scope is narrow and each argument is sound in isolation. This asks the
composition question: a call denied by BOTH obligations, with BOTH bases
present.

The sink is CATASTROPHIC (`drop_database`, built-in table) and declared an
integrity sink. Its driving argument is enum-covered, and its value arrives from
an untrusted web read — so the attacker chooses the target, but only from the
operator's approved set.
"""
from __future__ import annotations

import asyncio

from _corepath import RecordingHandler, envelope, say, tool_event

from axor_core.capability.executor import CapabilityExecutor
from axor_core.contracts.policy import EscalationPolicy, ExecutionPolicy, ToolPolicy
from axor_core.contracts.taint import TaintSource
from axor_core.node.intent_loop import IntentLoop
from axor_core.policy.value_policy import ValuePredicate
from axor_core.taint.causal_root import CausalRoot

SINK = "drop_database"
# Names long enough for the per-value ledger to track them: a short token like
# "prod" is below the engine's tracking threshold and would silently arrive
# untainted, which would make this matrix measure nothing.
APPROVED = frozenset({"analytics-staging-01", "analytics-prod-01"})
CHOSEN = "analytics-prod-01"                  # attacker picks, from the enum

VALUE_POLICIES = {SINK: [ValuePredicate(arg="name", kind="enum", allowed=APPROVED)]}
DRIVING = {SINK: ["name"]}


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        name="p",
        tool_policy=ToolPolicy(allow_read=True, extra_allowed=(SINK, "fetch_page")),
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=(SINK,),
            max_escalations=2, max_ops_per_grant=5,
            require_human=True,                # a human DOES approve the grant
        ),
    )


async def _attempt(*, supersession: bool, grant: bool) -> tuple[bool, str, bool]:
    """One cell of the matrix. Returns (approved, reason, handler_ran)."""
    handler = RecordingHandler(SINK)
    cap = CapabilityExecutor()
    cap.register(handler)

    loop = IntentLoop(
        cap, [],
        value_policies=VALUE_POLICIES if supersession else {},
        driving_args=DRIVING,
        integrity_sinks={SINK},                # the obligation supersession lifts
        escalation_callback=(lambda *a, **k: _approve()) if grant else None,
    )
    # The target value is attacker-chosen: it arrives from an untrusted read.
    loop._taint_engine.register_value(CHOSEN, CausalRoot.external_read(TaintSource.WEB))

    env = envelope(_policy())
    if grant:
        g = await loop._handle_escalation(
            tool_event("escalate_policy", {"tool": SINK, "reason": "ops asked", "max_ops": 1}),
            env)
        assert g.get("granted") is True, g

    resolved = await loop._resolve_tool_intent(tool_event(SINK, {"name": CHOSEN}), env)
    return resolved.approved, resolved.reason, bool(handler.log)


async def _approve() -> bool:
    return True


async def main() -> None:
    rows = {}
    for supersession in (False, True):
        for grant in (False, True):
            rows[(supersession, grant)] = await _attempt(supersession=supersession, grant=grant)

    for (sup, gr), (ok, reason, ran) in rows.items():
        label = f"supersession={'on ' if sup else 'off'} grant={'on ' if gr else 'off'}"
        print(f"      {label} -> approved={ok!s:5s} ran={ran!s:5s} {reason[:62]!r}")

    neither = rows[(False, False)][0]
    only_sup = rows[(True, False)][0]
    only_grant = rows[(False, True)][0]
    both, _, both_ran = rows[(True, True)]

    say("Z1 two bases compose into a lift neither one grants",
        (not neither) and (not only_sup) and (not only_grant) and both and both_ran,
        f"neither={neither} supersession_only={only_sup} grant_only={only_grant} "
        f"both={both} (handler ran={both_ran})")


asyncio.run(main())
