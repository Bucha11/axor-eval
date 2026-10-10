#!/usr/bin/env python3
"""The proposed composition rule, tested on the pairs the matrix found dangerous.

`basis_pairs.py` measured that composition on its own is near-trivial (two
obligations deny, each basis lifts one), and that the attacker-chosen subset is
exactly the pairs containing SUPERSESSION — the only basis that admits a SET of
values rather than one effect.

RULE (proposed): when a set-admitting basis participates in a recovery, the
widening must be bound to the argument values the authorising party actually saw.
`axor_core.taint.grants` already stores exactly that (a witness id and the
(sink, argument) positions it licenses), so the rule is a conjunction with the
kernel's own decision:

    admit  ⟺  kernel_admits(call)  ∧  jointly_granted(sink, args, driving_args)

PRE-REGISTERED predictions, written before the run:

  B1  the approver saw one enum member, the run drives another → the kernel still
      admits (as measured), the grant check refuses, so the conjunction refuses.
  B2  the approver saw the member the run drives → the conjunction admits, i.e.
      the rule does not kill the recovery it is protecting.
  B3  a pair with no set-admitting basis needs no binding, so the rule leaves
      GRANT+CLEARANCE exactly as the kernel decided — the rule must not
      over-deny.

What this does NOT show: that correct bindings can be *obtained*. Here the
approval names the values, which is what an approval dialog, an operator lease or
a declared enum gives you. The earlier objection to per-argument identity — that
issuance cannot be derived from free text, which carries no attribution signal
(`tests/taint/test_task_trust_is_mention_based.py`) — does not apply to a
recovery basis, because a basis is structured by construction. It would apply
again the moment anyone tried to mint bindings from prose.
"""
from __future__ import annotations

import asyncio

from _corepath import say

from axor_core.taint.grants import Grant, GrantIndex
from basis_pairs import BASH, DROP, attempt

SINK = DROP.tool
DRIVING = frozenset({DROP.enum_arg})
SEEN_BY_APPROVER = "analytics-staging-01"      # what the human actually approved
RUN_DRIVES = DROP.args[DROP.enum_arg]          # "analytics-prod-01", from the read


def _index(bound_value: str) -> GrantIndex:
    index = GrantIndex()
    index.issue(Grant.of("approval-1", SINK, {DROP.enum_arg: bound_value}))
    return index


async def main() -> None:
    pair = frozenset({"SUPERSESSION", "GRANT"})

    # B1 — the approver saw staging, the run drives prod.
    kernel_ok, _reason, _ran = await attempt(DROP, pair)
    bound_ok = _index(SEEN_BY_APPROVER).jointly_granted(SINK, DROP.args, DRIVING)
    say("B1 a widening bound to what the approver saw refuses the substitution",
        kernel_ok and not bound_ok and not (kernel_ok and bound_ok),
        f"kernel admits={kernel_ok} (unchanged), grant check={bound_ok}, "
        f"conjunction={kernel_ok and bound_ok} — approver saw {SEEN_BY_APPROVER!r}, "
        f"run drives {RUN_DRIVES!r}")

    # B2 — same machinery, the approver saw the value the run drives.
    bound_ok2 = _index(RUN_DRIVES).jointly_granted(SINK, DROP.args, DRIVING)
    say("B2 and admits the recovery it is meant to protect",
        kernel_ok and bound_ok2,
        f"kernel admits={kernel_ok}, grant check={bound_ok2}, "
        f"conjunction={kernel_ok and bound_ok2}")

    # B3 — a pair with no set-admitting basis: the rule asks for no binding.
    bash_ok, _r, _ran2 = await attempt(BASH, frozenset({"GRANT", "CLEARANCE"}))
    say("B3 the rule does not touch a pair that delegates no set",
        bash_ok is True,
        f"GRANT+CLEARANCE on a call with no driving set: kernel={bash_ok}, "
        "binding not required, so the conjunction equals the kernel decision")


asyncio.run(main())
