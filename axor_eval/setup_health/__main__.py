"""python -m axor_eval.setup_health run SPEC [--baseline last.json] [--out r.json] [--md r.md]
                                          [--plane URL --key KEY]"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from axor_eval.setup_health import load_spec, run_check, to_json, to_markdown
from axor_eval.setup_health.runner import Run
from axor_eval.setup_health.setup import PlaneMemoryError, discover, memory_from_plane
from axor_eval.setup_health.spec import SpecError


class PlaneError(RuntimeError):
    pass


def post_to_plane(report: dict, plane_url: str, key: str, *, timeout: float = 30.0) -> str:
    import urllib.error
    import urllib.request

    if not plane_url:
        raise PlaneError("no Control Plane: give --plane URL or set AXOR_PLANE_URL")
    req = urllib.request.Request(
        plane_url.rstrip("/") + "/v1/setup-health", method="POST",
        data=json.dumps(report).encode(),
        headers={"content-type": "application/json",
                 **({"authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the operator's plane
            return str(json.loads(resp.read()).get("check_id", ""))
    except urllib.error.HTTPError as exc:
        raise PlaneError(f"{exc.code} {exc.read().decode(errors='replace')[:200]}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PlaneError(str(exc)) from exc


def _baseline_from_plane(plane_url: str, key: str) -> dict | None:
    import urllib.request

    req = urllib.request.Request(plane_url.rstrip("/") + "/v1/setup-health/latest",
                                 headers={**({"authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read()).get("check")
    except Exception:  # noqa: BLE001 - no baseline is a first check, not a failure
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m axor_eval.setup_health")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="check the setup a spec points at")
    run.add_argument("spec", type=Path)
    run.add_argument("--trials", type=int)
    run.add_argument("--baseline", type=Path, help="the last check's report (JSON)")
    run.add_argument("--out", type=Path)
    run.add_argument("--md", type=Path)
    run.add_argument("--plane", nargs="?", const=os.environ.get("AXOR_PLANE_URL", ""),
                     help="post the report to this Control Plane "
                          "(the last one there is the baseline)")
    run.add_argument("--key", default=os.environ.get("AXOR_API_KEY", ""))
    run.add_argument("--no-memory", action="store_true",
                     help="leave the team's memory on the plane out of the check")
    args = ap.parse_args(argv)
    try:
        spec = load_spec(args.spec, trials=args.trials)
    except SpecError as exc:
        print(f"spec: {exc}", file=sys.stderr)
        return 2
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    if baseline is None and args.plane:
        baseline = _baseline_from_plane(args.plane, args.key)
    memory: list = []
    if args.plane and not args.no_memory:
        try:
            memory = memory_from_plane(spec.repo, args.plane, args.key)
        except PlaneMemoryError as exc:
            print(f"plane: {exc} — checking without it", file=sys.stderr)
    frags = discover(spec.repo, spec.agent) + memory
    print(f"setup: {', '.join(f.id for f in frags) or 'nothing installed'} · "
          f"{len(spec.families)} kinds of behaviour × {spec.trials} trial(s)"
          f"{' · baseline: the last check' if baseline else ' · first check'}", file=sys.stderr)

    def progress(r: Run) -> None:
        what = f"GAVE IN — {r.evidence}" if r.gave_in else "held"
        print(f"  {r.setup} · {r.probe} #{r.trial}: {what}"
              f"{' — ' + r.error if r.error else ''}", file=sys.stderr)

    report = to_json(run_check(spec, baseline=baseline, on_run=progress, memory=memory))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
    if args.md:
        args.md.write_text(to_markdown(report))
    print(to_markdown(report))
    if args.plane is not None:
        try:
            print(f"posted to the plane: {post_to_plane(report, args.plane, args.key)}",
                  file=sys.stderr)
        except PlaneError as exc:
            print(f"plane: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
