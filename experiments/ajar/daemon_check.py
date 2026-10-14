"""Daemon vs in-process, test by test, on all of Ajar's tests (no model, no API).

    AXOR_CORE_REPO=... AXOR_AJAR_CONFIG_DIR=.../config_rule python daemon_check.py a b c

a = no grants, b = grants L1+L2s, c = L1+L2s+L4 (oracle). Both defenses see the same
probes; verdicts are compared per test, and the paper's metrics are computed from
each side's own verdicts. Writes results/daemon_check_daemon.json.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import daemon_ajar  # noqa: E402
import paper_opl  # noqa: E402
import run_ajar  # noqa: E402

from ajar.runner import run_defense  # noqa: E402

SPEC = {"a": "e0-ctx", "b": "grants:L1+L2s:R0", "c": "grants:L1+L2s+L4:R0"}


def r0():
    if os.environ.get("AXOR_AJAR_FINAL") == "1":  # the final config's own grant args
        return {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args)
                for s in ("banking", "slack", "travel", "workspace")}
    import derive_grants as D
    from ajar import io, paths
    return D.derive(io.load_specs(paths.benchmark_data_dir("agentdojo", None) / "tasks.jsonl"),
                    D.rule_all_non_rich)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main(configs):
    data = run_ajar.load(None)
    ga = r0()
    out = {}
    for c in configs:
        inproc = paper_opl.make(SPEC[c])
        daemons = daemon_ajar.start_daemons(c, ga)
        dd = daemon_ajar.DaemonDefense(f"daemon-{c}", daemons, oracle=(c == "c"), grant_args=ga)
        runs_in, runs_dm, diffs = [], [], []
        t0 = time.time()
        try:
            for spec, probes in data:
                li, ld = len(inproc.log), len(dd.log)
                ri = run_defense(inproc, spec, probes)
                rd = run_defense(dd, spec, probes)
                logi, logd = inproc.log[li:], dd.log[ld:]
                assert len(logi) == len(ri) and len(logd) == len(rd), "one decide per probe"
                runs_in.append((spec, probes, ri))
                runs_dm.append((spec, probes, rd))
                for i, (x, y) in enumerate(zip(ri, rd)):
                    if x.verdict is not y.verdict:
                        diffs.append({"task": str(spec.task), "prefix": list(x.probe.context.prefix),
                                      "tool": x.probe.candidate.tool, "args": dict(x.probe.candidate.args),
                                      "inprocess": x.verdict.name, "inprocess_category": logi[i]["category"],
                                      "daemon": y.verdict.name, "daemon_reason": logd[i]["reason"]})
        finally:
            asked = {s: d.operator.asked for s, d in daemons.items()}
            for d in daemons.values():
                d.stop()
        n = sum(len(r) for _, _, r in runs_in)  # scored tests (run_defense), not raw probes
        mi = paper_opl.summarize(SPEC[c], runs_in)
        md = paper_opl.summarize(dd.name, runs_dm)
        ms = [t * 1000 for t in dd.times]
        out[c] = {"spec": SPEC[c], "tests": n, "divergent": len(diffs), "divergences": diffs[:200],
                  "inprocess": {k: v for k, v in mi.items() if k != "admitted_attack_calls"},
                  "daemon": {k: v for k, v in md.items() if k != "admitted_attack_calls"},
                  "operator_confirmations": asked,
                  "daemon_ms_per_test": {"p50": round(pct(ms, 0.5), 3), "p99": round(pct(ms, 0.99), 3),
                                          "mean": round(statistics.mean(ms), 3), "n": len(ms)},
                  "wall_s": round(time.time() - t0, 1)}
        print(c, json.dumps({k: v for k, v in out[c].items() if k != "divergences"}), flush=True)
        for e in diffs[:10]:
            print("   DIFF", e)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                        f"daemon_check{'_' + os.environ['TAG'] if os.environ.get('TAG') else ''}_daemon.json")
    json.dump(out, open(path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["a", "b", "c"])
