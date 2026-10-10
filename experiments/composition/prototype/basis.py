"""PROTOTYPE — a permission that carries the condition it was issued under.

Not a new principle. UCON (Park & Sandhu, usage control) already has continuity
of decisions, mutable attributes, ongoing authorization and revocation during
usage. The only thing being tried here is the concretization for agent recovery:
which OBSERVABLE conditions an agent permission can be conditioned on, and
whether a stale permission actually reaches a handler on real execution.

What this is NOT conditioned on, deliberately: any claim that a particular read
causally influenced a particular argument. Establishing that requires reasoning
through the LLM, which is where soundness collapsed before. Every condition below
is a counter or a version an auditor can read off the trace.

Conditions, and the event that loses each:

    policy version v        -> the authority-bearing fields of the policy changed
    degradation <= L        -> the session level went past L
    untrusted reads == n    -> the count of arming reads changed
    object version r        -> (not prototyped: needs trusted versioning)

The read counter is deliberately conservative: an unrelated read invalidates a
permission whose argument it never touched. That is a measurable utility cost,
reported as such, not a hidden semantic heuristic.

Also deliberately narrow: `valid` bounds FUTURE dispatch. It does not roll back
an effect already produced and does not unread anything from the context.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(
    0, os.environ.get("AXOR_CORE_REPO")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "axor-core")
)

from axor_core.contracts.policy import ExecutionPolicy          # noqa: E402
from axor_core.taint.grants import canonical                     # noqa: E402

#: Policy fields that carry authority. A change in any of them is a new version;
#: a change in a planning field (context_mode, compression) is not.
AUTHORITY_FIELDS = (
    "tool_policy", "allowed_paths", "export_mode", "child_mode", "max_child_depth",
    "max_unattended_consequence", "escalation_policy",
    "allowed_passthrough_commands", "allow_model_switch",
)


def policy_version(policy: ExecutionPolicy) -> str:
    """A version over the authority-bearing fields only."""
    parts = [f"{name}={getattr(policy, name)!r}" for name in AUTHORITY_FIELDS]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class SessionState:
    """Everything a condition may be checked against — all of it observable."""
    policy_version: str
    degradation_level: int
    untrusted_reads: int


@dataclass(frozen=True)
class Call:
    sink: str
    args: dict
    essential: tuple[str, ...]

    def fingerprint(self) -> tuple:
        return (self.sink,) + tuple(
            (n, canonical(self.args.get(n))) for n in sorted(self.essential)
        )


@dataclass
class Permission:
    """One recovery, with the call it covers and the conditions it was issued under."""
    permission_id: str
    call: tuple                       # the exact rendered call it covers
    issuer: str
    expires_at: float
    max_uses: int = 1
    used: int = 0
    # the declared conditions; None = not conditioned on this
    at_policy_version: str | None = None
    max_degradation: int | None = None
    at_untrusted_reads: int | None = None

    def check(self, call: tuple, state: SessionState, *, now: float | None = None,
              conditions: bool = True) -> tuple[bool, str]:
        """`conditions=False` gives the control column: one-shot binding to the
        exact call plus TTL, and nothing about the basis."""
        now = time.time() if now is None else now
        if call != self.call:
            return False, "call differs from the one this permission covers"
        if now >= self.expires_at:
            return False, "expired"
        if self.used >= self.max_uses:
            return False, f"spent ({self.used}/{self.max_uses})"
        if not conditions:
            return True, "bound call, within TTL and uses"
        if self.at_policy_version is not None and state.policy_version != self.at_policy_version:
            return False, "policy version changed since issuance"
        if self.max_degradation is not None and state.degradation_level > self.max_degradation:
            return False, (f"degradation level {state.degradation_level} past the declared "
                           f"bound {self.max_degradation}")
        if self.at_untrusted_reads is not None and state.untrusted_reads != self.at_untrusted_reads:
            return False, (f"untrusted-read count moved {self.at_untrusted_reads} -> "
                           f"{state.untrusted_reads}")
        return True, "basis holds"

    def consume(self) -> None:
        self.used += 1


@dataclass
class PermissionLedger:
    """Issuance, use and loss of basis, so a replay can re-derive the decision.

    The ledger is evidence. It is not the authority, and it is not what performs
    the revocation.
    """
    permissions: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def issue(self, p: Permission, state: SessionState) -> None:
        self.permissions[p.permission_id] = p
        self.events.append(("issued", p.permission_id, p.call, state))

    def decide(self, call: tuple, state: SessionState, *, conditions: bool = True,
               now: float | None = None) -> tuple[bool, str]:
        reasons = []
        for p in self.permissions.values():
            ok, why = p.check(call, state, now=now, conditions=conditions)
            if ok:
                return True, p.permission_id
            reasons.append(f"{p.permission_id}: {why}")
            if conditions and "changed" in why or "past the declared" in why or "moved" in why:
                self.events.append(("basis_lost", p.permission_id, why))
        return False, "; ".join(reasons) or "no permission on record"


def atomic_boundary() -> str:
    """Where the condition is evaluated, stated once so the answer is definite.

    The check happens immediately before dispatch, on the same state snapshot the
    call is dispatched under. A change arriving after that snapshot does not
    retroactively deny an in-flight call — it is seen by the next check. An effect
    already produced is not revoked; only future dispatch is bounded.
    """
    return "immediately before dispatch, on the snapshot the call is dispatched under"
