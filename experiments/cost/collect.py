"""Inventory of token data in the recorded traces (no model calls).

Builds runs.parquet only if every trial can be given its own token counts. The
recorded traces cannot (see RESULTS.md): token usage is logged per LLM completion
in shared spend ledgers with no trial key, written by 6-12 concurrent processes.
This script prints the evidence for that and exits without writing runs.parquet.

    python experiments/cost/collect.py
"""
from __future__ import annotations

import glob
import json
import os
import tarfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AJAR_RUNS = os.environ.get("AJAR_AGENTDOJO_ROOT", "/home/user/ext/Ajar/bench/agentdojo") + "/runs"

# (label, trace archive, spend ledger)
SOURCES = [
    ("rope v1 gpt-4o-mini", "rope_rule/runs_axor_rule.tgz", "rope_rule/spend.jsonl"),
    ("rope v2 gpt-4o-mini", "rope_rule/runs_axor_rule2.tgz", "rope_rule/spend_v2.jsonl"),
    ("rope v3 gpt-4o-mini", "rope_rule/runs_axor_rule3.tgz", "rope_rule/spend_v3.jsonl"),
    ("live v4 o4-mini", "ajar/results/live_v4/trajectories.tgz", "ajar/results/live_v4/spend.jsonl"),
    ("live v5 o4-mini", "ajar/results/live_v5/trajectories.tgz", "ajar/results/live_v5/spend.jsonl"),
]


def ledger(path: str) -> dict:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    keys = Counter(tuple(sorted(r)) for r in rows)
    return {"completions": len(rows), "keys": [list(k) for k in keys],
            "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in rows),
            "reasoning_tokens": sum(int(r.get("reasoning_tokens") or 0) for r in rows),
            "cost_usd": round(sum(float(r.get("cost") or 0) for r in rows), 4)}


def traces(archive: str) -> dict:
    """Trials per cell, assistant messages, and the wall-clock span of each writer process
    (file mtimes in the archive) to show the ledgers were written concurrently."""
    cells: Counter = Counter()
    assistant = 0
    span: dict[str, list[int]] = defaultdict(list)
    with tarfile.open(archive) as tf:
        for m in tf.getmembers():
            if not m.name.endswith(".json"):
                continue
            d = json.load(tf.extractfile(m))
            attacked = bool(d.get("injection_task_id"))
            arm = d.get("pipeline_name", "governed" if d.get("governed") else "?")
            arm = arm.rsplit("-axor-", 1)[-1] if "-axor-" in arm else ("governed" if d.get("governed") else arm)
            suite = d.get("suite_name") or d.get("suite")
            cells[(suite, arm, attacked)] += 1
            assistant += sum(1 for x in d["messages"] if x["role"] == "assistant")
            writer = m.name.split("/")[1]
            span[f"{writer}|{'attack' if attacked else 'clean'}|{suite}"].append(m.mtime)
    # number of writers alive at the busiest moment
    events = sorted([(min(v), 1) for v in span.values()] + [(max(v), -1) for v in span.values()])
    alive = peak = 0
    for _, e in events:
        alive += e
        peak = max(peak, alive)
    return {"trials": sum(cells.values()), "assistant_msgs": assistant,
            "cells": {f"{s}|{a}|{'attacked' if t else 'clean'}": n for (s, a, t), n in sorted(cells.items())},
            "writers": len(span), "peak_concurrent_writers": peak}


def shipped_runs() -> dict:
    """AgentDojo's shipped runs (the paper's replay source): token fields present?"""
    out = {}
    for model in ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"):
        files = glob.glob(f"{AJAR_RUNS}/{model}/*/*/*/*.json")
        keys: Counter = Counter()
        msg_keys: Counter = Counter()
        for f in files[:200]:
            d = json.load(open(f))
            keys.update(d.keys())
            for x in d["messages"]:
                msg_keys.update(x.keys())
        out[model] = {"files": len(files), "run_keys": sorted(keys), "message_keys": sorted(msg_keys)}
    return out


def main() -> None:
    print("== traces with a token ledger")
    for label, arch, spend in SOURCES:
        t = traces(os.path.join(ROOT, arch))
        s = ledger(os.path.join(ROOT, spend))
        print(f"\n{label}: trials={t['trials']} assistant_msgs={t['assistant_msgs']} "
              f"ledger_completions={s['completions']} (diff {s['completions'] - t['assistant_msgs']:+d}) "
              f"writers={t['writers']} peak_concurrent={t['peak_concurrent_writers']}")
        print(f"  ledger fields: {s['keys']}")
        print(f"  ledger totals: prompt={s['prompt_tokens']:,} completion={s['completion_tokens']:,} "
              f"reasoning={s['reasoning_tokens']:,} cost=${s['cost_usd']}")
        print(f"  cells: {t['cells']}")
    print("\n== AgentDojo shipped runs (paper replay source)")
    for m, v in shipped_runs().items():
        print(f"  {m}: {v['files']} files; run keys {v['run_keys']}; message keys {v['message_keys']}")
    print("\nSTOP: no per-trial token counts (ledger lines carry no trial key and were written by "
          "concurrent processes); runs.parquet not written. See RESULTS.md.")


if __name__ == "__main__":
    main()
