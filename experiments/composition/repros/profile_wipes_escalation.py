#!/usr/bin/env python3
"""What does a profile do to escalation?

`Profile.escalation_policy` is applied as an overlay CEILING: `_intersect_escalation`
(composer.py:18-32) keeps only the tools present in both the per-task policy and
the overlay. Both shipped overlays — `_HUMAN_ESCALATION` and `_AUTO_ESCALATION`
(profiles.py:30-36) — declare `allow_escalation=True` with limits, and leave
`grantable_tools` at its default `()`.

As a ceiling, `()` means "nothing is grantable". So selecting any profile, the
default `balanced` included, intersects every policy's grantable list down to
empty while leaving `allow_escalation=True` in place: the composed policy
advertises escalation that can never grant a tool
("tool 'write' is not in grantable_tools", escalation.py:197-198).

The intersection itself is right. The defect is that an overlay has no way to say
"this overlay does not restrict the list" — unset and empty are the same value.
"""
from __future__ import annotations

from _corepath import say

from axor_core.policy import presets
from axor_core.policy.composer import PolicyComposer
from axor_core.profiles import DEFAULT_PROFILE, PROFILES

rows = {}
for name, profile in PROFILES.items():
    composed = PolicyComposer(
        consequence_ceiling=profile.consequence_ceiling,
        escalation_policy=profile.escalation_policy,
    ).compose(presets.readonly(), [])
    rows[name] = composed.escalation_policy

for name, ep in rows.items():
    print(f"      {name:9s} overlay.grantable={PROFILES[name].escalation_policy.grantable_tools} "
          f"-> composed allow={ep.allow_escalation} grantable={ep.grantable_tools} "
          f"max_escalations={ep.max_escalations}")

say("Y1 every profile empties grantable_tools while keeping allow_escalation=True",
    all(ep.allow_escalation and not ep.grantable_tools for ep in rows.values()),
    f"per-task policy declared grantable_tools={presets.readonly().escalation_policy.grantable_tools}; "
    f"default profile is {DEFAULT_PROFILE!r}")
