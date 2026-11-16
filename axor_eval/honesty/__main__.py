"""python -m axor_eval.honesty run SPEC [--trials N] [--out report.json] [--md report.md]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from axor_eval.honesty import load_spec, run_eval, to_json, to_markdown
from axor_eval.honesty.runner import Trial
from axor_eval.honesty.spec import SpecError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m axor_eval.honesty")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the honesty eval a spec describes")
    run.add_argument("spec", type=Path)
    run.add_argument("--trials", type=int)
    run.add_argument("--out", type=Path)
    run.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec, trials=args.trials)
    except SpecError as exc:
        print(f"spec: {exc}", file=sys.stderr)
        return 2
    print(f"{spec.runs} agent runs: {len(spec.arms)} arm(s) × {len(spec.breaks)} break(s) × "
          f"{len(spec.tasks)} task(s) × {spec.trials} trial(s)", file=sys.stderr)

    def progress(t: Trial) -> None:
        print(f"  {t.arm} · {t.broke} · #{t.trial}: {t.verdict}"
              f"{' — ' + t.error if t.error else ''}", file=sys.stderr)

    trials = run_eval(spec, on_trial=progress)
    md = to_markdown(spec, trials)
    if args.out:
        args.out.write_text(json.dumps(to_json(spec, trials), indent=2))
    if args.md:
        args.md.write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
