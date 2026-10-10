#!/usr/bin/env python3
"""Does composition between policies really narrow every axis?

`PolicyComposer.apply_parent_restrictions` is the federation invariant ("a parent
can never grant a child more than it has itself", composer.py:159-169) and
`_validate_child_policy` is the explicit second net at spawn time ("so any
regression is caught immediately rather than silently producing an
over-privileged child", wrapper.py:231-237).

This measures both nets, axis by axis. The positive result matters as much as
the gap: 11 of 12 axes are intersected correctly.
"""
from __future__ import annotations

from _corepath import say

from axor_core.contracts.canonical import ConsequenceClass
from axor_core.contracts.policy import (
    ChildMode, CompressionMode, ContextMode, EscalationPolicy, ExecutionPolicy,
    ExportMode, ToolPolicy,
)
from axor_core.errors.exceptions import SpawnValidationError
from axor_core.node.spawn import _validate_child_policy
from axor_core.policy import presets
from axor_core.policy.composer import PolicyComposer
from axor_core.profiles import PROFILES

C = ConsequenceClass

# ── 1. the consequence ceiling is not among the intersected fields ───────────

parent = ExecutionPolicy(name="parent", max_unattended_consequence=C.REVERSIBLE,
                         max_child_depth=2,
                         tool_policy=ToolPolicy(allow_read=True, allow_spawn=True))
child = ExecutionPolicy(name="child", max_unattended_consequence=C.CATASTROPHIC,
                        tool_policy=ToolPolicy(allow_read=True))

composed = PolicyComposer().apply_parent_restrictions(child, parent)
say("P1 apply_parent_restrictions skips the consequence ceiling",
    composed.max_unattended_consequence is C.CATASTROPHIC,
    f"parent={parent.max_unattended_consequence.name} "
    f"child={child.max_unattended_consequence.name} -> "
    f"composed={composed.max_unattended_consequence.name}")

try:
    _validate_child_policy(child, parent, child_depth=1)
    say("P2 the spawn validator skips it too", True,
        "child CATASTROPHIC under a REVERSIBLE parent accepted, no error")
except SpawnValidationError as exc:
    say("P2 the spawn validator skips it too", False, f"raised: {exc}")

# ── 2. the deployment overlay assigns where its docstring says it intersects ──

lowered = ExecutionPolicy(name="operator-lowered", max_unattended_consequence=C.REVERSIBLE)
widened = PolicyComposer(consequence_ceiling=C.CATASTROPHIC).compose(lowered, [])
say("P3 the deployment overlay replaces instead of narrowing",
    widened.max_unattended_consequence is C.CATASTROPHIC,
    f"per-task REVERSIBLE + overlay CATASTROPHIC -> {widened.max_unattended_consequence.name}; "
    "composer.py:83-85 claims it 'intersects with the per-task policy, never replaces it'")

policy_default = ExecutionPolicy().max_unattended_consequence
shipped = {n: (p.consequence_ceiling.name if p.consequence_ceiling else None)
           for n, p in PROFILES.items()}
say("P4 shipped profiles that widen rather than narrow",
    any(p.consequence_ceiling and p.consequence_ceiling > policy_default
        for p in PROFILES.values()),
    f"policy default={policy_default.name}; profiles={shipped}")

end_to_end = PolicyComposer(consequence_ceiling=C.CATASTROPHIC).compose(
    presets.readonly(), [], parent_policy=parent)
say("P5 compose() end to end keeps the widened ceiling",
    end_to_end.max_unattended_consequence > parent.max_unattended_consequence,
    f"parent={parent.max_unattended_consequence.name} -> "
    f"child={end_to_end.max_unattended_consequence.name}")

# ── 3. the axes that ARE intersected (the positive half) ─────────────────────

narrow = ExecutionPolicy(
    name="p",
    tool_policy=ToolPolicy(allow_read=True, allow_write=False, allow_bash=False,
                           extra_allowed=("send_money",)),
    max_child_depth=1, export_mode=ExportMode.RESTRICTED,
    context_mode=ContextMode.MINIMAL, compression_mode=CompressionMode.AGGRESSIVE,
    child_mode=ChildMode.SHALLOW, child_context_fraction=0.1,
    escalation_policy=EscalationPolicy(allow_escalation=False),
    allowed_paths=("/srv/work",),
)
wide = ExecutionPolicy(
    name="c",
    tool_policy=ToolPolicy(allow_read=True, allow_write=True, allow_bash=True,
                           extra_allowed=("send_money", "wire_transfer")),
    max_child_depth=5, export_mode=ExportMode.FULL,
    context_mode=ContextMode.BROAD, compression_mode=CompressionMode.LIGHT,
    child_mode=ChildMode.ALLOWED, child_context_fraction=1.0,
    escalation_policy=EscalationPolicy(allow_escalation=True, grantable_tools=("bash",)),
    allowed_paths=("/",), allow_model_switch=True,
)
r = PolicyComposer().apply_parent_restrictions(wide, narrow)
held = {
    "allow_write": r.tool_policy.allow_write is False,
    "allow_bash": r.tool_policy.allow_bash is False,
    "extra_allowed": r.tool_policy.extra_allowed == ("send_money",),
    "max_child_depth": r.max_child_depth == 0,
    "export_mode": r.export_mode is ExportMode.RESTRICTED,
    "context_mode": r.context_mode is ContextMode.MINIMAL,
    "compression_mode": r.compression_mode is CompressionMode.AGGRESSIVE,
    "child_mode": r.child_mode is ChildMode.SHALLOW,   # parent SHALLOW is the ceiling
    "child_context_fraction": r.child_context_fraction == 0.1,
    "escalation": r.escalation_policy.allow_escalation is False,
    "allowed_paths": r.allowed_paths == ("/srv/work",),
    "allow_model_switch": r.allow_model_switch is False,
}
say("P6 every other axis narrows correctly", all(held.values()),
    f"{sum(held.values())}/{len(held)} hold; failures="
    f"{[k for k, v in held.items() if not v] or 'none'}")

# ── 4. how much the spawn-time validator re-checks ───────────────────────────

NARROW_PARENT = ExecutionPolicy(
    name="parent",
    tool_policy=ToolPolicy(allow_read=False, allow_search=False, allow_write=False,
                           allow_bash=False, allow_spawn=False),
    allowed_paths=("/srv/work",), max_child_depth=3,
    context_mode=ContextMode.MINIMAL, compression_mode=CompressionMode.AGGRESSIVE,
    child_mode=ChildMode.SHALLOW, export_mode=ExportMode.SUMMARY,
    max_unattended_consequence=C.REVERSIBLE,
    escalation_policy=EscalationPolicy(allow_escalation=False),
)
WIDENINGS = {
    "tool_policy.allow_read": dict(tool_policy=ToolPolicy(allow_read=True)),
    "tool_policy.allow_search": dict(tool_policy=ToolPolicy(allow_search=True)),
    "tool_policy.allow_write": dict(tool_policy=ToolPolicy(allow_write=True)),
    "tool_policy.allow_bash": dict(tool_policy=ToolPolicy(allow_bash=True)),
    "tool_policy.allow_spawn": dict(tool_policy=ToolPolicy(allow_spawn=True)),
    "tool_policy.extra_allowed": dict(tool_policy=ToolPolicy(extra_allowed=("send_money",))),
    "max_child_depth": dict(max_child_depth=9),
    "allowed_paths": dict(allowed_paths=("/",)),
    "escalation_policy": dict(escalation_policy=EscalationPolicy(
        allow_escalation=True, grantable_tools=("bash",))),
    "context_mode": dict(context_mode=ContextMode.BROAD),
    "compression_mode": dict(compression_mode=CompressionMode.LIGHT),
    "child_mode": dict(child_mode=ChildMode.ALLOWED),
    "max_unattended_consequence": dict(max_unattended_consequence=C.CATASTROPHIC),
    "allowed_passthrough_commands": dict(allowed_passthrough_commands=("/anything",)),
    "allow_model_switch": dict(allow_model_switch=True),
    "export_mode": dict(export_mode=ExportMode.FULL),
}
caught, missed = [], []
for axis, override in WIDENINGS.items():
    fields = dict(
        name="child", tool_policy=NARROW_PARENT.tool_policy,
        allowed_paths=NARROW_PARENT.allowed_paths, max_child_depth=1,
        context_mode=NARROW_PARENT.context_mode,
        compression_mode=NARROW_PARENT.compression_mode,
        child_mode=NARROW_PARENT.child_mode, export_mode=NARROW_PARENT.export_mode,
        max_unattended_consequence=NARROW_PARENT.max_unattended_consequence,
        escalation_policy=NARROW_PARENT.escalation_policy,
    )
    fields.update(override)
    try:
        _validate_child_policy(ExecutionPolicy(**fields), NARROW_PARENT, child_depth=1)
        missed.append(axis)
    except SpawnValidationError:
        caught.append(axis)
print(f"      validator re-checks {len(caught)}/{len(WIDENINGS)} axes: {caught}")
print(f"      not re-checked: {missed}")

# ── 5. when the gap is reachable ─────────────────────────────────────────────
# A profile ceiling is applied by the same composer to the parent's policy and to
# the child's freshly selected preset, so an operator-wide ceiling lands on both
# and the missing intersection is masked. The gap is reachable when the parent's
# lower ceiling comes from somewhere the child does not share — an explicit
# policy= / default_policy= — because the child node is always re-selected
# (wrapper.py:640-644 passes no override_policy).
overlaid_child = PolicyComposer(consequence_ceiling=C.REVERSIBLE).compose(
    presets.readonly(), [], parent_policy=parent)
explicit_child = PolicyComposer().compose(presets.readonly(), [], parent_policy=parent)
say("P7 an operator-wide profile ceiling masks the gap; an explicit policy does not",
    overlaid_child.max_unattended_consequence is C.REVERSIBLE
    and explicit_child.max_unattended_consequence is C.CONSEQUENTIAL,
    f"with overlay -> child={overlaid_child.max_unattended_consequence.name}; "
    f"no overlay, parent REVERSIBLE -> child={explicit_child.max_unattended_consequence.name}")
