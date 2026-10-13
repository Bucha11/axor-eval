"""ROPE (xhOwenMa/ROPE) behind Ajar's Defense protocol, with argument provenance.

Per decision, the same construction as axor_ajar.AxorDefense: fresh ROPE state, the
executed plan prefix replayed in AgentDojo, every step's output filed by ROPE's own
OriginTracker (structured records under their unforgeable sender, blobs as injectable),
the task's policy compiled from the audited floor + the cached router's TaskScope for
this prompt (rope.policy_synthesis.compile_policy), and the candidate checked by ROPE's
Enforcer. Tools outside the floor are always allowed, as in RoutedPolicyBootstrap.

The cached router (scopes/<router>/<suite>.json) is a table keyed by the prompt, so the
verdicts are deterministic: no LLM call, one run is the measurement. ROPE has floors
for banking, slack and travel only; workspace is not covered.

    ROPE_SRC=/path/to/ROPE/src python paper_opl.py rope:opus
"""
from __future__ import annotations

import dataclasses
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.environ.get("ROPE_SRC", "/home/user/ext/ROPE/src"))

import axor_ajar  # noqa: E402  (PREFIXES: the cached prefix executor)

from agentdojo.functions_runtime import FunctionCall  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from ajar.core.ir import TaskSpec  # noqa: E402
from ajar.core.types import Candidate, ContextRef, Verdict  # noqa: E402
from rope import origin as O  # noqa: E402
from rope import policy_synthesis as PS  # noqa: E402
from rope.enforce import Enforcer  # noqa: E402
from rope.scopes_io import load_router_scopes  # noqa: E402

from check_wrapper import VERSIONS  # noqa: E402

SUITES = ("banking", "slack", "travel")


@dataclasses.dataclass
class RopeDefense:
    name: str
    router: str = "opus"
    privilege_surface: tuple[str, ...] = ("TOOL", "PARAMETER", "PROVENANCE")
    log: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    decisions: int = 0
    missing_scope: set = dataclasses.field(default_factory=set)
    _cache: dict = dataclasses.field(default_factory=dict)

    def _suite(self, suite: str):
        hit = self._cache.get(suite)
        if hit is None:
            floor, scopes = load_router_scopes(self.router, suite)
            s = get_suite(VERSIONS[suite], suite)
            tools = [{"name": t.name, "description": t.description,
                      "args": t.parameters.model_json_schema().get("properties", {})} for t in s.tools]
            hit = self._cache[suite] = (floor, scopes, tools)
        return hit

    def prepare(self, spec: TaskSpec, llm=None) -> TaskSpec:
        return spec

    def decide(self, spec: TaskSpec, ctx: ContextRef, cand: Candidate) -> Verdict:
        suite = spec.task.suite
        if suite not in SUITES:
            raise ValueError(f"ROPE has no floor for suite {suite!r}")
        floor, scopes, tools = self._suite(suite)
        origin_map: dict = {}
        tracker = O.OriginTracker(origin_map)
        messages = []
        for i, (call, out) in enumerate(axor_ajar.PREFIXES.outputs(spec, ctx)):
            fc = FunctionCall(function=call.tool, args=dict(call.args), id=f"p{i}")
            # a failed step reaches the model as an error with empty content, as live
            messages.append({"role": "tool", "content": out if out is not None else "", "tool_call": fc})
        tracker.query(spec.prompt, None, None, messages, {})
        scope = scopes.get(spec.prompt)
        enf = Enforcer()
        enf.update_available_tools(tools)
        enf.set_user_query(spec.prompt)
        if scope is None:  # as RoutedPolicyBootstrap: state-changing tools blocked
            self.missing_scope.add(str(spec.task))
            policy = {}
        else:
            policy = PS.compile_policy(floor, scope, origin_map=origin_map,
                                       prompt_ids=O.tokenize_identifiers(spec.prompt))
        enf.update_security_policy(policy)
        enf.update_always_allowed_tools([t["name"] for t in tools if t["name"] not in floor])
        try:
            enf.check_tool_call(cand.tool, dict(cand.args))
            allowed = True
        except Exception:  # noqa: BLE001  (ROPE signals a denial by raising)
            allowed = False
        self.decisions += 1
        self.log.append({"ctx": ctx.label, "prefix": list(ctx.prefix), "tool": cand.tool, "allowed": allowed})
        return Verdict.ALLOW if allowed else Verdict.DENY
