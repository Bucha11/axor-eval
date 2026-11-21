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


class PlaneError(RuntimeError):
    pass


def post_to_plane(report: dict, plane_url: str, key: str, *, timeout: float = 30.0) -> str:
    """POST the report to ``{plane}/v1/skill-evals``; the eval id it is stored under."""
    import urllib.error
    import urllib.request

    if not plane_url:
        raise PlaneError("no Control Plane: give --plane URL or set AXOR_PLANE_URL")
    req = urllib.request.Request(
        plane_url.rstrip("/") + "/v1/skill-evals", method="POST",
        data=json.dumps(report).encode(),
        headers={"content-type": "application/json",
                 **({"authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the operator's plane
            return str(json.loads(resp.read()).get("eval_id", ""))
    except urllib.error.HTTPError as exc:
        raise PlaneError(f"{exc.code} {exc.read().decode(errors='replace')[:200]}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PlaneError(str(exc)) from exc


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
    run.add_argument("--plane", nargs="?", const="", metavar="URL",
                     help="post the report to the Control Plane (default: $AXOR_PLANE_URL; "
                          "key: the ones `axor-wrap connect` saved) — it shows under Skill evals")
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
    report = to_json(spec, results)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.plane is not None:
        try:
            from axor_eval.plane_connection import ingest_key, plane_url

            eval_id = post_to_plane(report, args.plane or plane_url(), ingest_key())
        except PlaneError as exc:
            print(f"error: the report was not posted: {exc}", file=sys.stderr)
            return 1
        print(f"on the Control Plane: Skill evals → {eval_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
