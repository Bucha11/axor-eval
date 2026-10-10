"""PROTOTYPE — an approval that authorises an EFFECT, not a tool class.

Why this exists. axor's consequence obligation is defined over effects: a ceiling
on how irreversible a single call may be without a governance gate. The basis
that lifts it binds something else entirely — the approver is asked
`(tool_use_id, tool, paths, max_ops)` (`axor_core/node/escalation.py:226-228`,
`EscalationCallback`, `intent_loop.py:113`), so for a sink whose effect is
determined by a non-path parameter (a recipient, an amount, a database name) the
approval cannot express the effect it is approving. `paths` shows the design
already reaching for parameter binding and stopping at one parameter kind.

So the gap is not an approval bypass. It is a missing contract: the obligation is
per effect, the authorisation is per tool.

The shape of the fix, stated as replacement rather than removal. A recovery basis
must not switch an obligation off; it must substitute an authority check over the
same effect:

    admits_consequence(e) ⟺ class(e) ≤ ceiling  ∨  valid_approval(a, e, now)

`valid_approval` is the checkable object: it names the sink, the ESSENTIAL
parameter values the approver saw, who issued it, when it expires, and how many
uses remain. An enum then attests membership of a value in an operator list, and
an approval attests authorisation of this action — and neither completes the
other's missing authority.

Two things this module deliberately keeps separate from the authorisation itself:

* **The ledger is evidence, not authority.** `ApprovalLedger` records issuance,
  use, expiry and revocation so a replay can re-derive the decision. axor today
  emits only ESCALATION_GRANTED / ESCALATION_DENIED (`contracts/trace.py:49-50`):
  `_PendingConsumption.commit` decrements counters with no event, and an expired
  lease is deleted with no event (`escalation.py:72-78, 116-124`). "There was an
  approval" is not a substitute for an approval object, and a replay that cannot
  see use and expiry cannot check one.
* **Binding must reach execution.** `effect_fingerprint` is taken over the
  essential parameters at check time and verified at the handler boundary, so a
  mutation between the check and the call is refused rather than silently
  executed.

Not wired into the kernel. It is a prototype of a contract, and where the shape
settles it belongs in `axor_core` beside `taint/grants.py`.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(
    0, os.environ.get("AXOR_CORE_REPO")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "axor-core")
)

from axor_core.contracts.canonical import ConsequenceClass        # noqa: E402
from axor_core.policy.consequence import consequence_class        # noqa: E402
from axor_core.taint.grants import canonical                      # noqa: E402

#: Authority kinds a consequence lift may rest on. An automated policy is not one:
#: nobody saw the effect, so there is nothing to bind the approval to.
HUMAN_AUTHORITIES = frozenset({"human_operator", "trusted_boundary"})


@dataclass(frozen=True)
class Effect:
    """What is about to happen, at the granularity the obligation is defined on."""
    sink: str
    args: dict
    essential: tuple[str, ...]      # the parameters that determine this effect

    def fingerprint(self) -> tuple:
        """Identity of the effect over its essential parameters only."""
        return (self.sink,) + tuple(
            (name, canonical(self.args.get(name))) for name in sorted(self.essential)
        )


@dataclass
class Approval:
    """One authorisation of one effect, with its own lifetime."""
    approval_id: str
    sink: str
    bound: dict                     # essential parameter values the approver saw
    issuer: str                     # authority type, not a free-text label
    expires_at: float
    max_uses: int = 1
    used: int = 0
    revoked: bool = False

    def covers(self, effect: Effect) -> str | None:
        """None when this approval authorises `effect`, else why it does not."""
        if self.sink != effect.sink:
            return f"approval names sink {self.sink!r}, call is {effect.sink!r}"
        for name in sorted(effect.essential):
            if name not in self.bound:
                return f"approval does not bind essential parameter {name!r}"
            want, got = canonical(self.bound[name]), canonical(effect.args.get(name))
            if want is None or want != got:
                return (f"essential parameter {name!r}: approved "
                        f"{self.bound[name]!r}, call uses {effect.args.get(name)!r}")
        return None


@dataclass
class ApprovalLedger:
    """Approvals plus the lifecycle a replay has to be able to see."""
    approvals: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def issue(self, approval: Approval) -> None:
        self.approvals[approval.approval_id] = approval
        self.events.append(("issued", approval.approval_id, approval.sink,
                            dict(approval.bound), approval.issuer))

    def revoke(self, approval_id: str) -> None:
        a = self.approvals.get(approval_id)
        if a is not None and not a.revoked:
            a.revoked = True
            self.events.append(("revoked", approval_id))

    def valid_approval(
        self, effect: Effect, *, now: float | None = None,
        accept: frozenset[str] = HUMAN_AUTHORITIES,
    ) -> tuple[bool, str]:
        """Is there an approval authorising THIS effect, right now?

        Does not consume: consumption happens at execution, so an effect refused
        by a later gate burns nothing (the same discipline as
        `_PendingConsumption`).
        """
        now = time.time() if now is None else now
        reasons = []
        for a in self.approvals.values():
            if a.revoked:
                reasons.append(f"{a.approval_id}: revoked")
                continue
            if a.issuer not in accept:
                reasons.append(f"{a.approval_id}: issuer {a.issuer!r} cannot lift this")
                continue
            if now >= a.expires_at:
                self.events.append(("expired", a.approval_id))
                reasons.append(f"{a.approval_id}: expired")
                continue
            if a.used >= a.max_uses:
                reasons.append(f"{a.approval_id}: exhausted ({a.used}/{a.max_uses})")
                continue
            mismatch = a.covers(effect)
            if mismatch is not None:
                reasons.append(f"{a.approval_id}: {mismatch}")
                continue
            return True, a.approval_id
        return False, "; ".join(reasons) or "no approval on record"

    def consume(self, approval_id: str, effect: Effect) -> None:
        a = self.approvals[approval_id]
        a.used += 1
        self.events.append(("used", approval_id, effect.fingerprint(), a.used, a.max_uses))


def admits_consequence(
    effect: Effect, ceiling: ConsequenceClass, ledger: ApprovalLedger,
    *, operation: str | None = None, overrides: dict | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    """`class(e) ≤ ceiling ∨ valid_approval(a, e, now)`.

    The obligation is never switched off: over the ceiling, the call needs an
    authority over THIS effect.
    """
    cls = consequence_class(effect.sink, operation, overrides)
    if cls <= ceiling:
        return True, f"{cls.name} within ceiling {ceiling.name}"
    ok, detail = ledger.valid_approval(effect, now=now)
    if ok:
        return True, f"{cls.name} over ceiling {ceiling.name}, approved by {detail}"
    return False, f"{cls.name} over ceiling {ceiling.name}, no valid approval ({detail})"


def execute_bound(effect: Effect, approved_fingerprint: tuple, handler_args: dict,
                  essential: tuple[str, ...]) -> tuple[bool, str]:
    """The binding has to reach the handler, not stop at the check.

    Re-derives the fingerprint from the arguments the handler is actually about to
    receive. A mutation between check and call is a refusal, not a silent
    execution.
    """
    actual = Effect(effect.sink, handler_args, essential).fingerprint()
    if actual != approved_fingerprint:
        return False, "essential parameters changed between the check and the call"
    return True, "essential parameters unchanged"
