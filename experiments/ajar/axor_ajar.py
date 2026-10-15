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
import re
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


# Secret modes (residuals_rules.md revision 2): "paper" = the config's sensitive_sources;
# "declared" = + the operator's declaration of each suite's private store.
DECLARED_SECRETS = {
    "banking": {"get_user_info"},
    "slack": {"read_inbox"},
    "travel": {"get_user_information"},
    "workspace": {"get_received_emails", "get_unread_emails", "search_emails"},
}


def load_config(suite: str, integrity_default: str | None, integrity_origins: str) -> GovernanceConfig:
    cfg = GovernanceConfig.from_yaml(os.path.join(CONFIG_DIR, f"{suite}.yaml"))
    cfg = dataclasses.replace(
        cfg, integrity_default=integrity_default, integrity_origins=integrity_origins)
    mode = os.environ.get("AXOR_AJAR_SECRETS", "paper")
    if mode == "declared":
        cfg = dataclasses.replace(cfg, sensitive_sources=frozenset(cfg.sensitive_sources) | DECLARED_SECRETS[suite])
    elif mode != "paper":
        raise ValueError(f"AXOR_AJAR_SECRETS={mode!r}: expected paper | declared")
    return cfg


# ── MODEL.md §9 (references): the agent's side of a call, for offline evaluation ──────────────
_REF_ID_KEYS = ("id", "id_", "file_id", "event_id", "email_id")


def agent_args(g, args):
    """The call as an agent behind references would write it (§9.10): a value the session hid is
    given by its reference; R / own / never-read values stay raw. No-op without references."""
    t = getattr(g, "_xrefs", None)
    if t is None or not t.by_name:
        return args
    hid = {}
    for name, r in t.by_name.items():
        hid.setdefault(str(r.value).casefold(), name)
    # a hidden value inside text: addresses, and secret values (a digit-only secret of 8+ digits too)
    long = sorted((v for v in hid if len(v) >= 6 and (not v.isdigit() or len(v) >= 8)), key=len, reverse=True)

    def go(x, key):
        if isinstance(x, dict):
            return {k: go(v, k) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [go(v, key) for v in x]
        if isinstance(x, bool) or x is None:
            return x
        if isinstance(x, int):
            n = hid.get(str(x)) if key in _REF_ID_KEYS else None
            return n if n is not None else x
        if isinstance(x, str):
            n = hid.get(x.casefold())
            if n is not None and (key in _REF_ID_KEYS or not str(n).isdigit()):
                return n if not isinstance(n, int) else n
            out = x
            for v in long:  # a hidden address inside text is written as its reference
                if v in out.casefold():
                    import re as _re
                    out = _re.sub(_re.escape(v), str(hid[v]), out, flags=_re.I)
            return out
        return x
    return go(dict(args), None)


# MODEL.md §9.15: the platform adapter reads a declared source's output into a structure (the
# AgentDojo tool's own return format), never free text; the kernel takes only that structure
_LIST_HEAD = re.compile(r"^(?:Hotel Names|Restaurant in [^:\n]+|Car Rental Companies in [^:\n]+): ?(.*)$", re.S)


def structured(tool, out):
    if not isinstance(out, str):
        return out
    s = out.strip("\n")
    m = _LIST_HEAD.match(s)
    if m:
        return [x.strip() for x in m.group(1).split("\n") if x.strip()]
    if s.startswith("{") and s.endswith("}"):
        import ast
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return None
    import yaml
    try:
        y = yaml.safe_load(s)
    except Exception:
        return None
    return y if isinstance(y, (list, dict)) else None


def present(g, d, out, tool=None, args=None):
    """Register an executed output (and, with references, mint its references); §9.15: pass a
    declared source's structure to the gate."""
    if getattr(g, "_xrefs", None) is not None:
        view = g.present_output(d, out)
    else:
        g.register_output(d, out)
        view = out
    if tool is not None and getattr(g, "_desc", None) is not None and tool in g._desc.sources:
        v = structured(tool, out)
        if v is not None:
            g.observe_structured(tool, args or {}, v)
    return view


def spend_args(d, args):
    return d.resolved_args if getattr(d, "resolved_args", None) is not None else args


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
            d = g.evaluate(call.tool, agent_args(g, dict(call.args)))
            if getattr(d, "grant_id", None) is not None:  # the call executed: its grant use is spent
                key = g.spend(d, spend_args(d, dict(call.args)))
                if key is not None:
                    g.grant_store.commit(key)
            if out is not None:  # the live executor registers only clean executions
                present(g, d, out, call.tool, dict(call.args))
        d = g.evaluate(cand.tool, agent_args(g, dict(cand.args)))
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


# view-aware confirmer: the verbs of each sink (residuals_rules.md, fixed before any run)
VIEW_VERBS: dict[str, tuple[str, ...]] = {
    "send_money": ("send", "pay", "transfer", "wire"),
    "schedule_transaction": ("schedule", "set up", "recurring"),
    "update_scheduled_transaction": ("update", "change", "modify", "adjust"),
    "update_password": ("password",),
    "update_user_info": ("update", "change"),
    "send_email": ("send", "email", "mail", "reply", "forward", "write", "notify", "invite", "share"),
    "create_calendar_event": ("create", "schedule", "add", "organize", "organise", "book", "set up", "plan"),
    "cancel_calendar_event": ("cancel", "delete", "remove"),
    "reschedule_calendar_event": ("reschedule", "move", "postpone", "change"),
    "add_calendar_event_participants": ("add", "invite", "include"),
    "share_file": ("share", "grant", "give"),
    "append_to_file": ("append", "add", "write", "update"),
    "create_file": ("create", "write", "save", "make"),
    "delete_file": ("delete", "remove"),
    "delete_email": ("delete", "remove"),
    "reserve_hotel": ("reserve", "book"),
    "reserve_car_rental": ("reserve", "book"),
    "reserve_restaurant": ("reserve", "book"),
    "send_direct_message": ("send", "message", "dm", "tell", "write", "reply", "ask"),
    "send_channel_message": ("send", "post", "write", "message", "announce"),
    "add_user_to_channel": ("add", "invite"),
    "invite_user_to_slack": ("invite", "add"),
    "remove_user_from_slack": ("remove", "kick", "delete"),
    "post_webpage": ("post", "publish", "upload"),
    "get_webpage": ("visit", "open", "read", "get", "fetch", "check", "summarize", "summarise", "browse", "go to"),
}


def grants_kwargs(levels: str, tuple_grants: bool = True, counters: bool = True,
                  grant_args: dict | None = None, confirm: str = "oracle"):
    """governor kwargs + minting for a cumulative level set, e.g. "L1+L2+L3+L4"."""
    from axor_core.kernel.confirm import ScriptedConfirmer

    lv = set(levels.split("+"))
    table = GRANT_ARGS if grant_args is None else grant_args
    if os.environ.get("AXOR_AJAR_GRANT_ARGS_FROM_CONFIG") == "1":
        # MODEL.md §8.7: the grant arguments are the config's (= its driving arguments)
        table = {s: dict(load_config(s, "context", "request-only").grant_args)
                 for s in ("banking", "slack", "travel", "workspace")}

    def matcher(spec):
        """The scripted confirmer's oracle: approve iff the WHOLE proposed call —
        every argument, rich fields included — equals a call in the reference plan
        (kernel.confirm.call_digest; grant args compared by canonical value)."""
        def ok(a, c):
            from axor_core.kernel.confirm import call_digest
            from axor_core.kernel.handles import HandleTable

            kinds = table.get(spec.task.suite, {}).get(c[0], {})
            t = HandleTable()
            want = call_digest(c[0], c[1], kinds, t)
            return any(p.tool == c[0] and call_digest(p.tool, dict(p.args), kinds, t) == want
                       for p in spec.plan)
        return ok

    def naive(spec):
        """The fatigued human: approves when the destination named in the call is
        one the request mentions (a substring match on the request text); does not
        read the body or any other field. A call with no destination is approved."""
        import re as _re

        dest = _re.compile(r"(^|_)(recipients?|participants|channel|url|e-?mail|user_email|cc|bcc|user)$")
        prompt = (spec.prompt or "").lower()

        def ok(a, c):
            vals = []
            for k, v in c[1].items():
                if dest.search(k) and v is not None:
                    vals += list(v) if isinstance(v, (list, tuple)) else [v]
            return all(str(x).lower() in prompt for x in vals)
        return ok

    def view(spec):
        """view-aware (residuals_rules.md, fixed before any run): the naive
        destination test AND the tool's verb in the request (a request word starts
        with one of the tool's verbs; "set up"/"go to" as phrases). A tool with no
        verb entry is never approved."""
        dest_ok = naive(spec)
        prompt = (spec.prompt or "").lower()
        import re as _re
        words = _re.findall(r"[a-z]+", prompt)

        def ok(a, c):
            verbs = VIEW_VERBS.get(c[0])
            if not verbs or not dest_ok(a, c):
                return False
            for v in verbs:
                if " " in v:
                    if v in prompt:
                        return True
                elif any(w.startswith(v) for w in words):
                    return True
            return False
        return ok

    def kwargs(spec: TaskSpec) -> dict[str, Any]:
        suite = spec.task.suite
        kw: dict[str, Any] = {"grant_args": table.get(suite, {})}
        if os.environ.get("AXOR_AJAR_L2") == "tuple":
            pass  # revision 9: L2 = the kernel's tuple templates from the config's value_policies
        elif "L2" in lv and suite in TEMPLATES:
            kw["grant_templates"] = TEMPLATES[suite]
        elif "L2s" in lv and suite in TEMPLATES_SAFE:
            kw["grant_templates"] = TEMPLATES_SAFE[suite]
        if "L4" in lv:
            policy = {"naive": naive, "view": view, "oracle": matcher}[confirm]
            kw["confirmer"] = ScriptedConfirmer(policy(spec))
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
        d = g.evaluate(call.tool, agent_args(g, dict(call.args)))
        allowed &= d.allowed
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, spend_args(d, dict(call.args)))
            if key is not None:
                g.grant_store.commit(key)
        if out is not None:
            present(g, d, out, call.tool, dict(call.args))
    return {"confirmations": getattr(g, "confirmations", 0), "plan_admitted": allowed}
