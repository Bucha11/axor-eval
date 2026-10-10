#!/usr/bin/env python3
"""All pairs of widening bases: which pairs admit what neither admits, and why.

F10 showed one pair composing. This asks whether that is a property of pairs in
general, and whether a single rule predicts which pairs are dangerous. The
predictions below are PRE-REGISTERED: they are written before the runs, so the
rule is checked rather than fitted.

The four bases axor carries, with the obligation each lifts (W(a)):

  SUPERSESSION — W = {integrity}.  Premise: "the attacker can only ever choose a
                 value the operator approved" (gates.py:196-204).
  GRANT        — W = {consequence}. Premise: "a human authorised this
                 over-ceiling action" (require_human=True here, so a human really
                 is asked).
  CLEARANCE    — W = {degradation}.  Premise: "a governance authority reviewed the
                 session and judged it clean" (clear_by_governance requires a
                 GovernanceAuthority, engine.py:410-432).
  CEILING      — W = {consequence}.  Premise: none per call — the operator raised
                 the ceiling statically, ambiently, for every call in the session.

The candidate rule (pre-registered): a pair is DANGEROUS when one basis admits a
SET of values the attacker can choose within, and the other lifts the obligation
that would otherwise have put someone in front of the specific choice. Disjoint
scopes do not help: {integrity} and {consequence} are disjoint and compose.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from _corepath import RecordingHandler, envelope, say, tool_event

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

# Values long enough for the per-value ledger to track them; a short token sits
# below its threshold and would arrive untainted, making a cell vacuous.
DB_APPROVED = frozenset({"analytics-staging-01", "analytics-prod-01"})
DB_CHOSEN = "analytics-prod-01"
PATH_APPROVED = frozenset({"/srv/app/config-staging.yaml", "/srv/app/config-prod.yaml"})
PATH_CHOSEN = "/srv/app/config-prod.yaml"

AUTHORITY = GovernanceAuthority(
    authority_id="ops-oncall", authority_type="human_operator",
    reason_code="reviewed", audit_id="a1",
)


async def _approve() -> bool:
    return True


@dataclass(frozen=True)
class Scenario:
    """One call that two obligations both refuse, plus how to lift each."""
    name: str
    tool: str
    args: dict
    tainted: str | None          # value registered as coming from an untrusted read
    enum_arg: str | None         # the driving arg SUPERSESSION would cover
    enum_allowed: frozenset
    ceiling: ConsequenceClass    # the policy ceiling when CEILING basis is off
    raised_ceiling: ConsequenceClass
    integrity_sink: bool
    locked: bool                 # whether the session starts at LOCKED
    tool_policy: ToolPolicy


DROP = Scenario(
    name="drop_database", tool="drop_database", args={"name": DB_CHOSEN},
    tainted=DB_CHOSEN, enum_arg="name", enum_allowed=DB_APPROVED,
    ceiling=C.CONSEQUENTIAL, raised_ceiling=C.CATASTROPHIC,
    integrity_sink=True, locked=False,
    tool_policy=ToolPolicy(allow_read=True, extra_allowed=("drop_database",)),
)
WRITE = Scenario(
    name="write", tool="write", args={"path": PATH_CHOSEN, "content": "x"},
    tainted=PATH_CHOSEN, enum_arg="path", enum_allowed=PATH_APPROVED,
    ceiling=C.CONSEQUENTIAL, raised_ceiling=C.CATASTROPHIC,
    integrity_sink=True, locked=True,
    tool_policy=ToolPolicy(allow_read=True, allow_write=True),
)
BASH = Scenario(
    name="bash", tool="bash", args={"command": "echo hi"},
    tainted=None, enum_arg=None, enum_allowed=frozenset(),
    ceiling=C.REVERSIBLE, raised_ceiling=C.CATASTROPHIC,
    integrity_sink=False, locked=True,
    tool_policy=ToolPolicy(allow_read=True, allow_bash=True),
)
# Same call without the degradation obligation. Needed for the GRANT+CEILING
# pair: with the session LOCKED, a third obligation neither basis lifts would
# deny every cell and the pair would measure nothing. (The first run of this
# matrix made exactly that mistake.)
BASH_UNLOCKED = Scenario(
    name="bash (not locked)", tool="bash", args={"command": "echo hi"},
    tainted=None, enum_arg=None, enum_allowed=frozenset(),
    ceiling=C.REVERSIBLE, raised_ceiling=C.CATASTROPHIC,
    integrity_sink=False, locked=False,
    tool_policy=ToolPolicy(allow_read=True, allow_bash=True),
)


async def attempt(sc: Scenario, bases: frozenset[str]) -> tuple[bool, str, bool]:
    handler = RecordingHandler(sc.tool)
    cap = CapabilityExecutor()
    cap.register(handler)

    engine = None
    if sc.locked:
        engine = DegradationEngine()
        engine._transition_to(DegradationLevel.LOCKED, source_id=None,
                              trigger_intent="t", reason="repro")
        if "CLEARANCE" in bases:
            engine.clear_by_governance(AUTHORITY, "reviewed by oncall")

    supersede = "SUPERSESSION" in bases and sc.enum_arg is not None
    loop = IntentLoop(
        cap, [],
        value_policies=(
            {sc.tool: [ValuePredicate(arg=sc.enum_arg, kind="enum", allowed=sc.enum_allowed)]}
            if supersede else {}
        ),
        driving_args={sc.tool: [sc.enum_arg]} if sc.enum_arg else {},
        integrity_sinks={sc.tool} if sc.integrity_sink else set(),
        degradation_engine=engine,
        escalation_callback=(lambda *a, **k: _approve()) if "GRANT" in bases else None,
    )
    if sc.tainted is not None:
        loop._taint_engine.register_value(
            sc.tainted, CausalRoot.external_read(TaintSource.WEB))

    policy = ExecutionPolicy(
        name="p", tool_policy=sc.tool_policy,
        max_unattended_consequence=sc.raised_ceiling if "CEILING" in bases else sc.ceiling,
        escalation_policy=EscalationPolicy(
            allow_escalation=True, grantable_tools=(sc.tool,),
            max_escalations=2, max_ops_per_grant=5, require_human=True),
    )
    env = envelope(policy)

    if "GRANT" in bases:
        g = await loop._handle_escalation(
            tool_event("escalate_policy", {"tool": sc.tool, "reason": "ops", "max_ops": 1}), env)
        assert g.get("granted") is True, g

    r = await loop._resolve_tool_intent(tool_event(sc.tool, sc.args), env)
    return r.approved, r.reason, bool(handler.log)


# (pair, scenario, pre-registered verdict, why)
PAIRS = [
    (("SUPERSESSION", "GRANT"), DROP, "DANGEROUS",
     "enum admits a set the attacker picks from; the grant removes the human from this call's argument"),
    (("SUPERSESSION", "CEILING"), DROP, "DANGEROUS",
     "same set, and the ceiling was raised ambiently — nobody looks at any call"),
    (("SUPERSESSION", "CLEARANCE"), WRITE, "DANGEROUS",
     "enum admits a set; clearance restores the tool a compromised session had lost"),
    (("GRANT", "CLEARANCE"), BASH, "BENIGN",
     "no set is delegated: a human approved this tool and an authority reviewed the session"),
    (("GRANT", "CEILING"), BASH_UNLOCKED, "NO-OP",
     "scopes coincide ({consequence}); either basis alone already lifts it"),
    (("CLEARANCE", "CEILING"), BASH, "DANGEROUS",
     "the ceiling is ambient and the clearance restores the tool: no one examines this call"),
]


def _attacker_chose(sc: Scenario) -> bool:
    """Is the admitted effect selected by a value the attacker influenced?

    Measured, not assumed: the driving value is registered from an untrusted read
    and the engine is asked whether the call's driving root is tainted.
    """
    if sc.tainted is None:
        return False
    loop = IntentLoop(CapabilityExecutor(), [],
                      driving_args={sc.tool: [sc.enum_arg]} if sc.enum_arg else {})
    loop._taint_engine.register_value(sc.tainted, CausalRoot.external_read(TaintSource.WEB))
    return bool(loop._taint_engine.derive_value(sc.args).is_tainted)


async def main() -> None:
    print(f"{'pair':28s} {'none':>6s} {'a1':>6s} {'a2':>6s} {'both':>6s}  observed      predicted")
    results = {}
    for (a1, a2), sc, predicted, _why in PAIRS:
        cells = {}
        for bases in (frozenset(), frozenset({a1}), frozenset({a2}), frozenset({a1, a2})):
            cells[bases] = await attempt(sc, bases)
        none = cells[frozenset()][0]
        only1 = cells[frozenset({a1})][0]
        only2 = cells[frozenset({a2})][0]
        both, _reason, ran = cells[frozenset({a1, a2})]

        if both and not (none or only1 or only2):
            observed = "COMPOSES"            # the pair admits what neither admits
        elif both and (only1 or only2):
            observed = "NO-OP"               # one basis alone already admitted it
        elif not both:
            observed = "STILL DENIED"
        else:
            observed = "?"
        results[(a1, a2)] = (observed, predicted, ran, _attacker_chose(sc))
        print(f"{a1[:12]+'+'+a2[:12]:28s} {str(none):>6s} {str(only1):>6s} {str(only2):>6s} "
              f"{str(both):>6s}  {observed:12s}  {predicted}")

    # The rule is checked, not fitted: DANGEROUS must compose, NO-OP must not.
    rule_holds = all(
        (obs == "COMPOSES") if pred == "DANGEROUS"
        else (obs == "NO-OP") if pred == "NO-OP"
        else True
        for obs, pred, _, _ac in results.values()
    )
    composing = [f"{a}+{b}" for (a, b), (obs, *_r) in results.items() if obs == "COMPOSES"]
    print()
    say("W1 every pair predicted DANGEROUS composes, and the NO-OP pair does not",
        rule_holds, f"composing pairs: {composing}")
    # The pre-registered BENIGN pair is the interesting one: does it compose anyway?
    benign = [(k, v) for k, v in results.items() if v[1] == "BENIGN"]
    for k, (obs, _pred, _ran, _ac) in benign:
        say(f"W2 the pair predicted BENIGN ({k[0]}+{k[1]})", obs == "COMPOSES",
            f"observed={obs} — if it composes, 'both bases carry their own human' is NOT "
            "sufficient for safety and the rule needs the set/instance distinction")


    # ── the discriminator the first matrix did not measure ────────────────────
    # Composition on its own is close to trivial: two obligations deny, each
    # basis lifts one, so the pair admits the call. What separates the cases is
    # whether the ADMITTED EFFECT was chosen by an attacker-influenced value.
    print()
    print("      pair                         composes  attacker-chose-the-effect")
    for (a1, a2), (obs, _pred, _ran, attacker) in results.items():
        print(f"      {a1[:12]+'+'+a2[:12]:28s} {obs:9s} {attacker}")
    dangerous = {f"{a}+{b}" for (a, b), (obs, _p, _r, ac) in results.items()
                 if obs == "COMPOSES" and ac}
    say("W3 the attacker-chosen subset is exactly the pairs containing SUPERSESSION",
        dangerous == {"SUPERSESSION+GRANT", "SUPERSESSION+CEILING", "SUPERSESSION+CLEARANCE"},
        f"dangerous={sorted(dangerous)} — SUPERSESSION is the only basis that admits a SET "
        "of values rather than one effect, so it is the only one that can hand the choice "
        "to the run")


if __name__ == "__main__":        # importable: binding_rule.py reuses the scenarios
    asyncio.run(main())
