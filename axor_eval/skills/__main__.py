"""python -m axor_eval.skills run SPEC [--trials N] [--agent A] [--model M]
                                   [--out report.json] [--md report.md]

Prints how many agent runs the spec costs (tasks × arms × trials) first."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from axor_eval.skills.report import to_json, to_markdown
from axor_eval.skills.runner import describe, run_eval
from axor_eval.skills.spec import SpecError, load_spec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m axor_eval.skills",
        description="Which skills help, and what they cost? The same tasks with and without them.")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the eval a spec describes")
    run.add_argument("spec", type=Path)
    run.add_argument("--trials", type=int)
    run.add_argument("--agent", choices=["claude-code", "codex"])
    run.add_argument("--model")
    run.add_argument("--timeout", type=float)
    run.add_argument("--task", action="append", help="only this task (repeatable)")
    run.add_argument("--out", type=Path, help="write every trial and the summary as JSON")
    run.add_argument("--md", type=Path, help="write the summary table as Markdown")
    args = ap.parse_args(argv)

    try:
        spec = load_spec(args.spec, trials=args.trials, agent=args.agent, model=args.model,
                         timeout=args.timeout)
    except (SpecError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(describe(spec), file=sys.stderr)

    def progress(r) -> None:  # noqa: ANN001
        mark = "solved" if r.solved else "failed"
        extra = f" · {r.error}" if r.error else ""
        opened = ("" if r.opened is None or not r.skills
                  else f" · opened {', '.join(r.opened) or 'none'}")
        print(f"  {r.task} · {r.arm} · trial {r.trial}: {mark} · {r.total_tokens:,} tokens"
              f"{opened}{extra}", file=sys.stderr)

    results = run_eval(spec, on_trial=progress, tasks=args.task)
    md = to_markdown(spec, results)
    print(md)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.out:
        args.out.write_text(json.dumps(to_json(spec, results), indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
