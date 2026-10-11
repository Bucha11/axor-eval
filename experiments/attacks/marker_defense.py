"""Defence arm: can the host's instruction, or finer marking, stop the decode attack?

marker_search.py broke the sentinel gate with injections that never ask for the
sentinel to be removed. They put the attacker's value in the content in an ENCODED
form and have the agent DERIVE the plaintext, so no sentinel was ever on the string
the agent produced and the ledger has no fragment to match.

Two repairs suggest themselves, and this measures both, crossed:

  instruction  `preserve`  — today's: reproduce copied values exactly, sentinels
                             included.
               `strong`    — also covers values OBTAINED BY ANY OPERATION (decode,
                             reverse, arithmetic, concatenate, reformat, translate,
                             reconstruct): the agent must wrap the result itself. This
                             has to NAME the sentinel, since the agent now has to
                             produce it, and it pre-empts the framings the search
                             found (display artefact, relay corruption, annotation
                             disabled, export encoding).
  marking      `word`      — today's for this value class: the escape blob is a
                             single whitespace token, so the sentinel sits only on
                             its EDGES and stays behind with the discarded wrapper.
               `chunk2`    — marks INSIDE the blob, so the payload's own characters
                             carry sentinels.

Scored against the vectors the search already found, so this is a direct
before/after on a known break rather than a fresh search.

Note what `strong` costs even if it works: the agent becomes the labeller, deciding
which of its own outputs are derived. That is a behavioural property of the model,
which is the class arXiv 2510.09023 defeats — so a win here is a higher bar, not a
guarantee.

    OPEN_ROUTER_API_KEY=... python experiments/attacks/marker_defense.py
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from marker_adaptive import (  # noqa: E402
    MARKER,
    Trial,
    run_trial,
)
from marker_adaptive import (
    PRESERVE_STRONG as _PRESERVE_STRONG,
)
from marker_carriage import _PRESERVE, MARKERS  # noqa: E402
from marker_search import FOUND_BYPASSES  # noqa: E402

MODELS = [m for m in os.environ.get(
    "AXOR_MARK_MODELS",
    "anthropic/claude-sonnet-5.5,google/gemini-3.8-flash").split(",") if m]
N_REPS = int(os.environ.get("AXOR_MARK_N", "3"))
MAX_WORKERS = int(os.environ.get("AXOR_MARK_WORKERS", "24"))
MODES = tuple(m for m in os.environ.get("AXOR_MARK_MODES", "word,chunk2").split(",") if m)

_SENT = MARKERS[MARKER]


DEFENCES = {"preserve": _PRESERVE, "strong": _PRESERVE_STRONG}
VECTORS = {f"v{i}:{v['mechanism']}": v["text"] for i, v in enumerate(FOUND_BYPASSES)}
VECTORS["control:none"] = ""


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:3.0f}% ({n}/{d})" if d else "   n/a"


def build() -> list[tuple[str, str, str, Trial]]:
    out = []
    for model in MODELS:
        for dname, dtext in DEFENCES.items():
            for mode in MODES:
                for vname, vtext in VECTORS.items():
                    for rep in range(N_REPS):
                        out.append((dname, mode, vname, Trial(
                            model, "iban", "custom" if vtext else "none", rep,
                            injection=vtext, system_extra=dtext, mode_override=mode)))
    return out


def main() -> None:
    out = os.environ.get("AXOR_MARK_OUT", "marker_defense.jsonl")
    work = build()
    print(f"{len(work)} calls → {out}", flush=True)
    rows = []
    with open(out, "w") as fh, ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(run_trial, t): (d, m, v) for d, m, v, t in work}
        for i, f in enumerate(as_completed(futs), 1):
            d, m, v = futs[f]
            r = f.result()
            rec = {"defence": d, "mode": m, "vector": v, "model": r.model,
                   "rep": r.rep, "ok": r.ok, "arg": r.arg,
                   "marker_hit": r.marker_hit, "ledger_hit": r.ledger_hit,
                   "value_ok": r.value_ok, "bypass": r.bypass, "error": r.error}
            rows.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 30 == 0 or i == len(work):
                print(f"  {i}/{len(work)}", flush=True)
    report(rows)


def report(rows: list[dict]) -> None:
    ok = [r for r in rows if r["ok"]]
    print(f"\ncompleted {len(ok)}/{len(rows)}")
    print("\n=== bypass rate: defence x marking ===")
    print(f"{'defence':10} {'mode':8} " + " ".join(f"{v[:16]:>18}" for v in VECTORS))
    for d in DEFENCES:
        for m in MODES:
            cells = []
            for v in VECTORS:
                sub = [r for r in ok if r["defence"] == d and r["mode"] == m
                       and r["vector"] == v]
                cells.append(_pct(sum(r["bypass"] for r in sub), len(sub)))
            print(f"{d:10} {m:8} " + " ".join(f"{c:>18}" for c in cells))

    print("\n=== pooled over the four attack vectors (control excluded) ===")
    for d in DEFENCES:
        for m in MODES:
            sub = [r for r in ok if r["defence"] == d and r["mode"] == m
                   and not r["vector"].startswith("control")]
            print(f"  {d:10} {m:8} bypass {_pct(sum(r['bypass'] for r in sub), len(sub))}"
                  f"  marker_hit {_pct(sum(r['marker_hit'] for r in sub), len(sub))}"
                  f"  value_ok {_pct(sum(r['value_ok'] for r in sub), len(sub))}")

    print("\n=== per model, pooled over vectors ===")
    for model in MODELS:
        for d in DEFENCES:
            sub = [r for r in ok if r["model"] == model and r["defence"] == d
                   and not r["vector"].startswith("control")]
            print(f"  {model.split('/')[1][:18]:19} {d:10} "
                  f"bypass {_pct(sum(r['bypass'] for r in sub), len(sub))}")

    print("\n=== control arm (no attack): does `strong` break normal operation? ===")
    for d in DEFENCES:
        for m in MODES:
            sub = [r for r in ok if r["defence"] == d and r["mode"] == m
                   and r["vector"].startswith("control")]
            print(f"  {d:10} {m:8} marker_hit {_pct(sum(r['marker_hit'] for r in sub), len(sub))}"
                  f"  value_ok {_pct(sum(r['value_ok'] for r in sub), len(sub))}")

    print("\n=== sample arguments under `strong` ===")
    seen = set()
    for r in ok:
        k = (r["defence"], r["mode"], r["vector"])
        if r["defence"] == "strong" and k not in seen:
            seen.add(k)
            print(f"  {r['mode']:8} {r['vector'][:22]:23} bypass={int(r['bypass'])} "
                  f"| {r['arg'][:58]!r}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        path = os.environ.get("AXOR_MARK_OUT", "marker_defense.jsonl")
        with open(path) as fh:
            report([json.loads(x) for x in fh if x.strip()])
    else:
        main()
