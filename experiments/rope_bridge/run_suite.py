"""Run axor origin config (or undefended) on any AgentDojo suite in ROPE's harness.

  python -m axor_rope.run_suite --suite slack  --mode clean  --governed --origin
  python -m axor_rope.run_suite --suite travel --mode attack --governed --origin
  python -m axor_rope.run_suite --suite slack  --mode attack --undefended
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import openai
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import (benchmark_suite_with_injections,
                                 benchmark_suite_without_injections)
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from axor_rope.bridge import build_origin_pipeline, build_undefended_pipeline
from axor_rope.taxonomy import ORIGIN_TAXONOMIES

BENCH = "v1.2.2"
MODEL = os.environ.get("ROPE_AGENT_MODEL", "openai/gpt-4o-mini")
TAG = "gpt-4o-mini-2024-07-18-openrouter"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=list(ORIGIN_TAXONOMIES), required=True)
    ap.add_argument("--mode", choices=["clean", "attack"], required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--governed", action="store_true")
    g.add_argument("--undefended", action="store_true")
    ap.add_argument("--origin", action="store_true")
    ap.add_argument("--limit-ut", type=int, default=None)
    ap.add_argument("--limit-it", type=int, default=None)
    ap.add_argument("--logdir", type=Path, default=Path(__file__).resolve().parents[2] / "runs_axor")
    args = ap.parse_args()

    client = openai.OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                           base_url="https://openrouter.ai/api/v1")
    llm = OpenAILLM(client, MODEL, temperature=0.0)
    suite = get_suite(BENCH, args.suite)

    cond = ("governed-origin" if (args.governed and args.origin)
            else "governed" if args.governed else "undefended")
    name = f"{TAG}-axor-{args.suite}-{cond}"
    if args.governed and args.origin:
        pipe = build_origin_pipeline(llm, ORIGIN_TAXONOMIES[args.suite], name=name)
    elif args.undefended:
        pipe = build_undefended_pipeline(llm, name=name)
    else:
        raise SystemExit("governed runs require --origin in this runner")

    uts = list(suite.user_tasks)[: args.limit_ut] if args.limit_ut else None
    its = list(suite.injection_tasks)[: args.limit_it] if args.limit_it else None
    print(f"[axor] {args.suite} {args.mode} {cond} model={MODEL} "
          f"uts={len(uts) if uts else 'all'} its={len(its) if its else 'all'}")

    with OutputLogger(str(args.logdir), live=None):
        if args.mode == "clean":
            res = benchmark_suite_without_injections(
                pipe, suite, user_tasks=uts, logdir=args.logdir,
                force_rerun=True, benchmark_version=BENCH)
        else:
            attack = load_attack("important_instructions", suite, pipe)
            res = benchmark_suite_with_injections(
                pipe, suite, attack, user_tasks=uts, injection_tasks=its,
                logdir=args.logdir, force_rerun=True, benchmark_version=BENCH)

    util = list(res["utility_results"].values())
    print(f"  utility (CU/UA): {100*sum(util)/len(util):.1f}%  n={len(util)}")
    if args.mode == "attack":
        sec = list(res["security_results"].values())
        print(f"  ASR: {100*sum(sec)/len(sec):.1f}%  n={len(sec)}")
    if args.governed:
        d = pipe._axor_bootstrap.denials
        print(f"  axor denials: {len(d)}  sample={d[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
