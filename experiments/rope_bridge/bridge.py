"""Wire axor's ToolCallGovernor into ROPE's AgentDojo (autodojo) harness in
STRICT mode, so axor is measured on the *same* suites/attacks/scoring as ROPE.

Design mirrors rope.pipeline.RoutedPolicyBootstrap:
  - one fresh ToolCallGovernor per task (carries the per-session taint ledger),
  - built in ExecutionMode.STRICT (require_tool_roles + require_egress_allowlist),
  - the STRICT egress allowlist is the ORACLE allowlist for this task (the
    recipients its ground-truth solution uses + the user's own established
    payees), i.e. the router leg is replaced by ground truth (operator choice),
  - runtime.run_function is monkey-patched to gate each call through
    governor.evaluate() and, on success, feed the output back via
    register_output() so the taint ledger + confidentiality floor advance.
"""
from __future__ import annotations

import sys
from types import MethodType

sys.path.insert(0, "/home/user/axor-core")

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, load_system_message
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, ToolsExecutor, tool_result_to_str

from axor_core.governor import ToolCallGovernor
from axor_core.policy.value_policy import enum


def build_oracle_allowlists(suite) -> dict[str, dict[str, list]]:
    """{user_task_PROMPT: {sink: [allowed recipients]}} from ground truth + the
    user's own established payees in the pre-task environment. Keyed by PROMPT so
    the bootstrap can look it up from the query at runtime."""
    env = suite.load_and_inject_default_environment({})
    # the user's own established payees (not attacker-writable): recipients that
    # already sit in the account's scheduled transactions before any task runs.
    established: set = set()
    bank = getattr(env, "bank_account", None)
    for coll in ("scheduled_transactions", "transactions"):
        for t in getattr(bank, coll, []) or []:
            r = getattr(t, "recipient", None)
            if r:
                established.add(r)
    sinks = ("send_money", "schedule_transaction", "update_scheduled_transaction")
    out: dict[str, dict[str, list]] = {}
    for ut in suite.user_tasks.values():
        recips: set = set(established)
        for c in ut.ground_truth(env):
            if c.function in sinks:
                r = c.args.get("recipient")
                if r is not None:
                    recips.add(r)
        out[ut.PROMPT] = {s: sorted(recips) for s in sinks}
    return out


class AxorOriginBootstrap(BasePipelineElement):
    """Per task: build a context-default-integrity governor with NO ground-truth
    allowlist, seed the user's request as trusted (register_task), and guard the
    runtime. Credential/PII writes are integrity_sinks; egress recipients are
    integrity-gated. A driving value the user wrote passes; one derived from
    attacker-writable content is tainted and denied — ROPE's PROMPT marker via the
    integrity axis, no oracle."""

    def __init__(self, taxonomy: dict):
        self.tax = taxonomy
        self.denials: list[str] = []

    def _build_governor(self) -> ToolCallGovernor:
        return ToolCallGovernor(
            require_tool_roles=True,            # keep unclassified-tool fail-closed
            require_egress_allowlist=False,     # no allowlist obligation
            integrity_default="context",        # value must trace to trusted origin
            egress_sinks=self.tax["egress_sinks"],
            integrity_sinks=self.tax["integrity_sinks"],
            driving_args=self.tax["driving_args"],
            untrusted_sources=self.tax["untrusted_sources"],
            sensitive_sources=self.tax["sensitive_sources"],
            benign_tools=self.tax["benign_tools"],
            consequence_overrides=self.tax.get("consequence_overrides") or {},
        )

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        extra_args = {} if extra_args is None else extra_args
        gov = self._build_governor()
        gov.register_task(query)                # seed the request as trusted (T1)
        denials = self.denials

        if getattr(runtime.run_function, "__name__", "") != "axor_guarded_run_function":
            original = runtime.run_function

            def axor_guarded_run_function(self_rt, call_env, function_name, args):
                decision = gov.evaluate(function_name, args)
                if not decision.allowed:
                    denials.append(f"{function_name}: {decision.category}")
                    return "", f"[axor denied] {decision.reason}"
                out, err = original(call_env, function_name, args)
                if not err:
                    try:
                        gov.register_output(decision, out)
                    except Exception:
                        pass
                return out, err

            runtime.run_function = MethodType(axor_guarded_run_function, runtime)
        return query, runtime, env, messages, extra_args


class AxorStrictBootstrap(BasePipelineElement):
    """Per task: build a STRICT governor with this task's oracle allowlist and
    guard the runtime through governor.evaluate()/register_output()."""

    def __init__(self, taxonomy: dict, allowlists: dict[str, dict[str, list]]):
        self.tax = taxonomy
        self.allowlists = allowlists
        self.denials: list[str] = []

    def _build_governor(self, query: str) -> ToolCallGovernor:
        per_task = self.allowlists.get(query, {})
        value_policies = {
            sink: [enum(self.tax["driving_args"][sink][0], per_task.get(sink, []))]
            for sink in self.tax["egress_sinks"]
        }
        return ToolCallGovernor(
            require_tool_roles=True,
            require_egress_allowlist=True,          # == ExecutionMode.STRICT
            egress_sinks=self.tax["egress_sinks"],
            driving_args=self.tax["driving_args"],
            value_policies=value_policies,
            untrusted_sources=self.tax["untrusted_sources"],
            sensitive_sources=self.tax["sensitive_sources"],
            benign_tools=self.tax["benign_tools"],
            consequence_overrides=self.tax.get("consequence_overrides") or {},
        )

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        extra_args = {} if extra_args is None else extra_args
        gov = self._build_governor(query)
        denials = self.denials

        if getattr(runtime.run_function, "__name__", "") != "axor_guarded_run_function":
            original = runtime.run_function

            def axor_guarded_run_function(self_rt, call_env, function_name, args):
                decision = gov.evaluate(function_name, args)
                if not decision.allowed:
                    denials.append(f"{function_name}: {decision.category}")
                    return "", f"[axor STRICT denied] {decision.reason}"
                out, err = original(call_env, function_name, args)
                if not err:
                    try:
                        gov.register_output(decision, out)
                    except Exception:
                        pass   # ledger update best-effort; never crash the run
                return out, err

            runtime.run_function = MethodType(axor_guarded_run_function, runtime)
        return query, runtime, env, messages, extra_args


def build_governed_pipeline(llm, suite, taxonomy, *, name="axor-strict"):
    allowlists = build_oracle_allowlists(suite)
    bootstrap = AxorStrictBootstrap(taxonomy, allowlists)
    loop = ToolsExecutionLoop([ToolsExecutor(tool_result_to_str), llm])
    pipe = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), bootstrap, llm, loop])
    pipe.name = name
    pipe._axor_bootstrap = bootstrap
    return pipe


def build_origin_pipeline(llm, taxonomy, *, name="axor-origin"):
    bootstrap = AxorOriginBootstrap(taxonomy)
    loop = ToolsExecutionLoop([ToolsExecutor(tool_result_to_str), llm])
    pipe = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), bootstrap, llm, loop])
    pipe.name = name
    pipe._axor_bootstrap = bootstrap
    return pipe


def build_undefended_pipeline(llm, *, name):
    loop = ToolsExecutionLoop([ToolsExecutor(tool_result_to_str), llm])
    pipe = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), llm, loop])
    pipe.name = name
    return pipe
