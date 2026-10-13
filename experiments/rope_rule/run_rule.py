"""axor (rule taxonomy, request-only, optional L1+L2s grants) in ROPE's harness.

ROPE's AgentDojo fork (xhOwenMa/ROPE, autodojo, v1.2.2), gpt-4o-mini via
OpenRouter, attack important_instructions — the setup of the earlier axor/ROPE
table (axor-eval branch claude/rope-axor-analysis-syszaz, experiments/rope_bridge).
Only the axor rows are re-measured:

  rule         config_rule/<suite>.yaml, context integrity, request-only, no grants
  rule-grants  the same + task-scoped grants L1 (request literals) + L2s (templates);
               no L4 (no confirmer in this harness)

Spend: every completion asks OpenRouter for its cost (usage.include) and appends it
to $ROPE_SPEND_LOG; a call is refused once the ledger reaches $ROPE_SPEND_CAP.

    cd $ROPE && PYTHONPATH=autodojo/src:src:runs python .../run_rule.py --suite banking --mode clean --arm rule
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from types import MethodType

HERE = Path(__file__).resolve().parent
AJAR = HERE.parent / "ajar"

import openai  # noqa: E402
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, load_system_message  # noqa: E402
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement  # noqa: E402
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage  # noqa: E402
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, ToolsExecutor, tool_result_to_str  # noqa: E402
from agentdojo.attacks.attack_registry import load_attack  # noqa: E402
from agentdojo.benchmark import benchmark_suite_with_injections, benchmark_suite_without_injections  # noqa: E402
from agentdojo.logging import OutputLogger  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402

from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

BENCH = "v1.2.2"
MODEL = os.environ.get("ROPE_AGENT_MODEL", "openai/gpt-4o-mini")
TAG = "gpt-4o-mini-2024-07-18-openrouter"


class SpendCap(RuntimeError):
    pass


def _spent(path: str) -> float:
    if not os.path.exists(path):
        return 0.0
    return sum(float(json.loads(l).get("cost") or 0.0) for l in open(path) if l.strip())


def metered(client: openai.OpenAI) -> openai.OpenAI:
    ledger = os.environ.get("ROPE_SPEND_LOG", "rope_spend.jsonl")
    cap = float(os.environ.get("ROPE_SPEND_CAP", "4"))
    create = client.chat.completions.create

    def wrapped(*a, **kw):
        if _spent(ledger) >= cap:
            raise SpendCap(f"spend cap ${cap:.2f} reached")
        eb = dict(kw.pop("extra_body", None) or {})
        eb["usage"] = {"include": True}
        resp = create(*a, extra_body=eb, **kw)
        u = getattr(resp, "usage", None)
        extra = (getattr(u, "model_extra", None) or {}) if u else {}
        with open(ledger, "a") as f:
            f.write(json.dumps({"cost": extra.get("cost"), "prompt_tokens": getattr(u, "prompt_tokens", None),
                                "completion_tokens": getattr(u, "completion_tokens", None)}) + "\n")
        return resp

    client.chat.completions.create = wrapped
    return client


class RuleBootstrap(BasePipelineElement):
    """Per task: a fresh governor from the rule config; the request registered as
    trusted and, with grants, minted into L1 grants; the runtime guarded."""

    def __init__(self, cfg: GovernanceConfig, grants: dict | None):
        self.cfg = cfg
        self.grants = grants
        self.denials: list[str] = []
        self.grant_hits: list[str] = []

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        extra_args = {} if extra_args is None else extra_args
        kw = self.cfg.as_governor_kwargs()
        if self.grants:
            kw.update(self.grants)
        gov = ToolCallGovernor(**kw)
        gov.register_task(query)
        if self.grants:
            gov.grants.from_request(query)
        denials = self.denials
        original = getattr(runtime, "_axor_original_run_function", None) or runtime.run_function
        runtime._axor_original_run_function = original

        def guarded(self_rt, call_env, function_name, args):
            d = gov.evaluate(function_name, args)
            if not d.allowed:
                denials.append(f"{function_name}: {d.category}")
                return "", f"[axor denied] {d.reason}"
            out, err = original(call_env, function_name, args)
            if getattr(d, "grant_id", None) is not None:
                self.grant_hits.append(function_name)
                key = gov.spend(d, dict(args))
                if key is not None:
                    gov.grant_store.commit(key)
            if not err:
                try:
                    gov.register_output(d, out)
                except Exception:
                    pass
            return out, err

        runtime.run_function = MethodType(guarded, runtime)
        return query, runtime, env, messages, extra_args


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["banking", "slack", "travel"], required=True)
    ap.add_argument("--mode", choices=["clean", "attack"], required=True)
    ap.add_argument("--arm", choices=["rule", "rule-grants"], required=True)
    ap.add_argument("--limit-ut", type=int, default=None)
    ap.add_argument("--limit-it", type=int, default=None)
    ap.add_argument("--logdir", type=Path, default=Path("runs_axor_rule"))
    a = ap.parse_args()

    cfg = GovernanceConfig.from_yaml(str(AJAR / "config_rule" / f"{a.suite}.yaml"))
    cfg = dataclasses.replace(cfg, integrity_default="context", integrity_origins="request-only")
    grants = None
    if a.arm == "rule-grants":
        ga = json.load(open(AJAR / "live" / "grant_args_R0.json")).get(a.suite, {})
        tpl = json.load(open(AJAR / "live" / "templates_L2s.json")).get(a.suite)
        grants = {"grant_args": ga, **({"grant_templates": tpl} if tpl else {})}

    client = metered(openai.OpenAI(api_key=os.environ["OPEN_ROUTER_API_KEY"].strip(),
                                   base_url="https://openrouter.ai/api/v1"))
    llm = OpenAILLM(client, MODEL, temperature=0.0)
    suite = get_suite(BENCH, a.suite)
    boot = RuleBootstrap(cfg, grants)
    loop = ToolsExecutionLoop([ToolsExecutor(tool_result_to_str), llm])
    pipe = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), boot, llm, loop])
    pipe.name = f"{TAG}-axor-{a.suite}-{a.arm}"

    uts = list(suite.user_tasks)[: a.limit_ut] if a.limit_ut else None
    its = list(suite.injection_tasks)[: a.limit_it] if a.limit_it else None
    print(f"[axor] {a.suite} {a.mode} {a.arm} uts={len(uts) if uts else 'all'} its={len(its) if its else 'all'}")
    with OutputLogger(str(a.logdir), live=None):
        if a.mode == "clean":
            res = benchmark_suite_without_injections(pipe, suite, user_tasks=uts, logdir=a.logdir,
                                                     force_rerun=True, benchmark_version=BENCH)
        else:
            attack = load_attack("important_instructions", suite, pipe)
            res = benchmark_suite_with_injections(pipe, suite, attack, user_tasks=uts, injection_tasks=its,
                                                  logdir=a.logdir, force_rerun=True, benchmark_version=BENCH)
    util = list(res["utility_results"].values())
    print(f"  utility: {100 * sum(util) / len(util):.1f}%  n={len(util)}")
    if a.mode == "attack":
        sec = list(res["security_results"].values())
        print(f"  raw ASR: {100 * sum(sec) / len(sec):.1f}%  n={len(sec)}")
    print(f"  denials: {len(boot.denials)} {boot.denials[:8]}")
    if grants:
        print(f"  grant args: {sorted(grants['grant_args'])}")
        print(f"  grant-admitted calls: {len(boot.grant_hits)} {boot.grant_hits[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
