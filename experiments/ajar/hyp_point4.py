"""MODEL.md §9.17, point 4: H-B under a compromised insider (bodies of records whose sender is in O are
attacker-written). Along each Ajar reference plan (H-B on), at every sink call of the plan (a decision
point): the identifiers proven by an own sender so far (origin named_sender), by kind; the sinks they
reach (a sink whose destination argument has that kind); k = the values the insider could choose among
(realized in the recorded data; unbounded in principle). Route-2 format: per suite, decision points,
k median / p90 / max."""
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axor_ajar  # noqa: E402
import paper_opl  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import ContextRef  # noqa: E402
from axor_core.kernel.handles import split_kind  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def main():
    d = paper_opl.make("grants:L1+L2s:R0")
    pts = []
    for spec, _ in run_ajar.load(None):
        cfg = axor_ajar.load_config(spec.task.suite, "context", "request-only")
        reach = defaultdict(list)  # kind -> [sink.arg]
        for sink, kinds in cfg.grant_args.items():
            for a in (cfg.destination_args or {}).get(sink, ()):
                if a in kinds:
                    reach[split_kind(kinds[a])[0]].append(f"{sink}.{a}")
        g = d.governor(spec)
        full = ContextRef(task=spec.task, prefix=tuple(range(len(spec.plan))))
        for call, out in axor_ajar.PREFIXES.outputs(spec, full):
            sinks = set(cfg.egress_sinks) | set(cfg.integrity_sinks)
            if call.tool in sinks and g._xrefs is not None:
                own = defaultdict(set)
                for r in g._xrefs.by_name.values():
                    if r.origin == "named_sender" and not g._xrefs.sender_named(str(r.value)):
                        own[r.kind].add(str(r.value))
                if own:
                    pts.append({"suite": spec.task.suite, "task": str(spec.task).split("/")[2].split("@")[0],
                                "at": call.tool, "by_kind": {k: sorted(v) for k, v in own.items()},
                                "k": sum(len(v) for v in own.values()),
                                "reachable": sorted({s for k in own for s in reach.get(k, ())})})
            dd = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
            if dd.allowed and dd.grant_id is not None:
                key = g.spend(dd, axor_ajar.spend_args(dd, dict(call.args)))
                if key is not None:
                    g.grant_store.commit(key)
            if out is not None:
                axor_ajar.present(g, dd, out, call.tool, dict(call.args))
    summ = {}
    for s in ("banking", "slack", "travel", "workspace", "all"):
        ks = [p["k"] for p in pts if s == "all" or p["suite"] == s]
        summ[s] = {"decision_points": len(ks), "k": [statistics.median(ks), pct(ks, 0.9), max(ks)] if ks else None,
                   "reachable": sorted({x for p in pts if s == "all" or p["suite"] == s for x in p["reachable"]})}
    print(json.dumps(summ, indent=1))
    json.dump({"summary": summ, "points": pts}, open(os.path.join(HERE, "results", "hyp", "point4_HB.json"), "w"),
              indent=1)


if __name__ == "__main__":
    main()
