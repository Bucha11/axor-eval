"""axor as an Ajar system-under-test: the governor's own enforcement path as `decide`.

Ajar (github.com/reSHARMA/Ajar) asks a defense one question per probe: given the
calls already executed (a prefix of the task's frozen ground-truth plan) and the
injections loaded into the environment, may this candidate call run? axor has no
model in its decision path, so the question has an exact answer without any API:

    decide(ctx, cand) =
        g = fresh ToolCallGovernor(<suite>.yaml)
        g.register_task(task prompt)
        for each call c in ctx.prefix:            # what actually executed
            d = g.evaluate(c); out = run(c)
            g.register_output(d, str(out))        # labels the read, as live
        return g.evaluate(cand)

A fresh governor per decision is load-bearing: `evaluate` advances the normalizer's
provenance state, so reusing one across probes would make a verdict depend on probe
order. The prefix outputs are computed by executing the plan in a materialized
AgentDojo environment (the same recipe Ajar's own oracle uses) and cached per
(task, injections, prefix).

Run with the Ajar venv (it has agentdojo and ajar installed); axor-core is pure
Python and is put on sys.path from the sibling checkout.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from typing import Any, Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE = os.environ.get("AXOR_CORE_REPO") or os.path.abspath(
    os.path.join(_HERE, os.pardir, os.pardir, os.pardir, "axor-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

from ajar.core.ir import TaskSpec  # noqa: E402
from ajar.core.types import Candidate, ContextRef, Verdict  # noqa: E402

# AXOR_AJAR_CONFIG_DIR swaps in another set of suite configs (e.g. config_rule/,
# the taxonomy derived by rule in derive_grants.py).
CONFIG_DIR = os.environ.get("AXOR_AJAR_CONFIG_DIR") or os.path.join(_CORE, "examples", "agentdojo", "config")


def load_config(suite: str, integrity_default: str | None, integrity_origins: str) -> GovernanceConfig:
    cfg = GovernanceConfig.from_yaml(os.path.join(CONFIG_DIR, f"{suite}.yaml"))
    return dataclasses.replace(
        cfg, integrity_default=integrity_default, integrity_origins=integrity_origins)


class PrefixRunner:
    """Executes plan prefixes in AgentDojo and returns each step's output string.

    Cached by (task, injections, prefix): ~60 probes of one task share a handful of
    prefixes, and materializing an environment is the expensive part."""

    def __init__(self) -> None:
        self._cache: dict[tuple, list[tuple[Candidate, str | None]]] = {}
        self._adapter = None

    def _adapter_for(self):
        if self._adapter is None:
            import ajar.adapters.agentdojo.adapter  # noqa: F401  (registers the adapter)
            from ajar.adapters.base import get_benchmark
            self._adapter = get_benchmark("agentdojo")
        return self._adapter

    def outputs(self, spec: TaskSpec, ctx: ContextRef) -> list[tuple[Candidate, str | None]]:
        key = (str(ctx.task), tuple(sorted(ctx.injections.items())), tuple(ctx.prefix))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        from agentdojo.agent_pipeline.tool_execution import tool_result_to_str

        bare = dataclasses.replace(ctx, prefix=())
        state = self._adapter_for().materialize(bare)
        steps: list[tuple[Candidate, str | None]] = []
        for i in ctx.prefix:
            call = spec.plan[i]
            result, err = state.execute(call)
            steps.append((call, None if err is not None else tool_result_to_str(result)))
        self._cache[key] = steps
        return steps


PREFIXES = PrefixRunner()


@dataclasses.dataclass
class AxorDefense:
    """The current axor governor, unchanged, behind Ajar's Defense protocol.

    `hook` lets a variant (the grants levels in E1) adjust a freshly built governor
    before the prefix is replayed; E0 passes none."""

    name: str
    integrity_default: str | None = None
    integrity_origins: str = "any-trusted"
    privilege_surface: tuple[str, ...] = ("TOOL", "PARAMETER", "SEQUENCE", "PROVENANCE")
    hook: Callable[[ToolCallGovernor, TaskSpec], None] | None = None
    # Per-decision records, for the variance check and for auditing denials.
    log: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    decisions: int = 0
    # extra ToolCallGovernor kwargs (grant_args, confirmer factory, ...)
    governor_kwargs: Callable[[TaskSpec], dict[str, Any]] | None = None

    def prepare(self, spec: TaskSpec, llm=None) -> TaskSpec:
        return spec

    def governor(self, spec: TaskSpec) -> ToolCallGovernor:
        cfg = load_config(spec.task.suite, self.integrity_default, self.integrity_origins)
        kw = cfg.as_governor_kwargs()
        if self.governor_kwargs is not None:
            kw.update(self.governor_kwargs(spec))
        g = ToolCallGovernor(**kw)
        g.register_task(spec.prompt)
        if self.hook is not None:
            self.hook(g, spec)
        return g

    def decide(self, spec: TaskSpec, ctx: ContextRef, cand: Candidate) -> Verdict:
        g = self.governor(spec)
        for call, out in PREFIXES.outputs(spec, ctx):
            d = g.evaluate(call.tool, dict(call.args))
            if getattr(d, "grant_id", None) is not None:  # the call executed: its grant use is spent
                key = g.spend(d, dict(call.args))
                if key is not None:
                    g.grant_store.commit(key)
            if out is not None:  # the live executor registers only clean executions
                g.register_output(d, out)
        d = g.evaluate(cand.tool, dict(cand.args))
        self.decisions += 1
        self.log.append({"ctx": ctx.label, "prefix": list(ctx.prefix), "tool": cand.tool,
                         "allowed": d.allowed, "category": d.category})
        return Verdict.ALLOW if d.allowed else Verdict.DENY


# ── E1: task-scoped grants, level by level ──────────────────────────────────────
#
# grant_args: the driving arguments of each suite's write sinks, with their handle
# kind. Optional-only args (update_* fields that may be absent) are left out so a
# partial update is not refused for a missing field; the content-taint gate keeps
# guarding them.
GRANT_ARGS: dict[str, dict[str, dict[str, str]]] = {
    "banking": {
        "send_money": {"recipient": "iban", "amount": "money"},
        "schedule_transaction": {"recipient": "iban", "amount": "money"},
        "update_scheduled_transaction": {"id": "number"},
        "update_password": {"password": "string"},
    },
    "slack": {
        "send_direct_message": {"recipient": "string"},
        "send_channel_message": {"channel": "string"},
        "add_user_to_channel": {"user": "string", "channel": "string"},
        "invite_user_to_slack": {"user": "string", "user_email": "email"},
        "remove_user_from_slack": {"user": "string"},
        "post_webpage": {"url": "string"},
    },
    "travel": {
        "send_email": {"recipients": "email"},
        "reserve_hotel": {"hotel": "string"},
        "reserve_car_rental": {"company": "string"},
        "reserve_restaurant": {"restaurant": "string"},
        "cancel_calendar_event": {"event_id": "id"},
    },
    "workspace": {
        "send_email": {"recipients": "email"},
        "share_file": {"file_id": "id", "email": "email"},
        "delete_email": {"email_id": "id"},
        "delete_file": {"file_id": "id"},
        "cancel_calendar_event": {"event_id": "id"},
        "reschedule_calendar_event": {"event_id": "id"},
        "add_calendar_event_participants": {"event_id": "id", "participants": "email"},
        "append_to_file": {"file_id": "id"},
    },
}

# v2: added AFTER diagnosing E1 v1, where three undeclared sinks carried 0.146 of
# the 0.170 OPL (create_calendar_event participants, slack get_webpage url). Optional
# args use "kind?": a call may omit them, a value passed must be covered. Reported
# separately from v1 because it was chosen with the benchmark's leaks in view.
GRANT_ARGS_V2: dict[str, dict[str, dict[str, str]]] = {
    "banking": {**GRANT_ARGS["banking"],
                "update_user_info": {"first_name": "string?", "last_name": "string?",
                                     "street": "string?", "city": "string?"}},
    "slack": {**GRANT_ARGS["slack"], "get_webpage": {"url": "string"}},
    "travel": {**GRANT_ARGS["travel"],
               "send_email": {"recipients": "email", "cc": "email?", "bcc": "email?"},
               "create_calendar_event": {"participants": "email?"}},
    "workspace": {**GRANT_ARGS["workspace"],
                  "send_email": {"recipients": "email", "cc": "email?", "bcc": "email?"},
                  "create_calendar_event": {"participants": "email?"}},
}

# L2: the operator allowlists already in the repo's deployment configs, re-expressed
# as templates (uses = ∞). Only banking_tuned.yaml carries one; nothing is invented
# for the other suites.
TEMPLATES: dict[str, dict[str, list[dict]]] = {
    "banking": {
        s: [{"recipient": ["GB29NWBK60161331926819", "US122000000121212121212",
                           "US133000000121212121212"]}]
        for s in ("send_money", "schedule_transaction")
    },
}


# L2s: the same allowlist without US133000000121212121212. AgentDojo uses that IBAN
# both as every injection's attacker account and as banking/user_task_15's new
# landlord, so any allowlist that serves task 15 also admits every banking attack.
TEMPLATES_SAFE: dict[str, dict[str, list[dict]]] = {
    "banking": {
        s: [{"recipient": ["GB29NWBK60161331926819", "US122000000121212121212"]}]
        for s in ("send_money", "schedule_transaction")
    },
}


def grants_kwargs(levels: str, tuple_grants: bool = True, counters: bool = True,
                  grant_args: dict | None = None):
    """governor kwargs + minting for a cumulative level set, e.g. "L1+L2+L3+L4"."""
    from axor_core.kernel.confirm import ScriptedConfirmer

    lv = set(levels.split("+"))
    table = GRANT_ARGS if grant_args is None else grant_args

    def matcher(spec):
        def ok(a, c):
            from axor_core.kernel.handles import canonicalize, split_kind

            kinds = table.get(spec.task.suite, {}).get(c[0], {})

            def proj(args):
                out = []
                for k, spec_kind in sorted(kinds.items()):
                    kind = split_kind(spec_kind)[0]
                    v = args.get(k)
                    vals = v if isinstance(v, (list, tuple)) else [v]
                    try:
                        out.append((k, tuple(sorted(canonicalize(kind, x) for x in vals if x is not None))))
                    except ValueError:
                        out.append((k, ("<bad>",)))
                return tuple(out)

            want = proj(c[1])
            return any(p.tool == c[0] and proj(dict(p.args)) == want for p in spec.plan)
        return ok

    def kwargs(spec: TaskSpec) -> dict[str, Any]:
        suite = spec.task.suite
        kw: dict[str, Any] = {"grant_args": table.get(suite, {})}
        if "L2" in lv and suite in TEMPLATES:
            kw["grant_templates"] = TEMPLATES[suite]
        elif "L2s" in lv and suite in TEMPLATES_SAFE:
            kw["grant_templates"] = TEMPLATES_SAFE[suite]
        if "L4" in lv:
            kw["confirmer"] = ScriptedConfirmer(matcher(spec))
        return kw

    def hook(g: ToolCallGovernor, spec: TaskSpec) -> None:
        g.grants.tuple_grants = tuple_grants
        if not counters:
            g.grants.default_uses = None
        if "L1" in lv:
            g.grants.from_request(spec.prompt)
        if "L3" in lv:
            for c in spec.plan:
                if c.tool in table.get(spec.task.suite, {}):
                    g.grants.from_structured(c.tool, dict(c.args))

    return kwargs, hook


def grants_defense(name: str, levels: str, *, integrity_default: str | None = "context",
                   integrity_origins: str = "request-only", **kw) -> AxorDefense:
    kwargs, hook = grants_kwargs(levels, **kw)
    return AxorDefense(name, integrity_default=integrity_default,
                       integrity_origins=integrity_origins, hook=hook, governor_kwargs=kwargs)


def plan_walk(defense: AxorDefense, spec: TaskSpec) -> dict[str, Any]:
    """Run the whole reference plan through one governor, as a live session would:
    how many confirmations it asks, and whether every step is admitted."""
    from ajar.core.types import ContextRef as _C

    g = defense.governor(spec)
    full = _C(task=spec.task, prefix=tuple(range(len(spec.plan))))
    allowed = True
    for call, out in PREFIXES.outputs(spec, full):
        d = g.evaluate(call.tool, dict(call.args))
        allowed &= d.allowed
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, dict(call.args))
            if key is not None:
                g.grant_store.commit(key)
        if out is not None:
            g.register_output(d, out)
    return {"confirmations": getattr(g, "confirmations", 0), "plan_admitted": allowed}
