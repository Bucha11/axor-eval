"""MODEL.md §9.13 risk bound on Ajar: attacks whose attacker-seeded sink call carries a reference of
named-sender origin (the gate treats that value as proven, as L1), and how many of them are admitted
without a human (mode b). Also the gain side on Ajar: required (ALLOW) calls that carry a
named-sender reference.

    AXOR_AJAR_CONFIG_DIR=config_m1_c9v2 AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 \
    AXOR_CORE_REPO=... python sender_risk.py OUT.json
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_opl  # noqa: E402
import run_ajar  # noqa: E402
from ajar.core.types import Label, Verdict  # noqa: E402
from ajar.runner import run_defense  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402

LAST = {}
_orig = ToolCallGovernor.evaluate


def _eval(self, tool, args):
    d = _orig(self, tool, args)
    LAST["origins"] = tuple(getattr(d, "reference_origins", ()) or ())
    return d


ToolCallGovernor.evaluate = _eval


def main(out):
    d = paper_opl.make("grants:L1+L2s:R0")
    by_attack = defaultdict(lambda: {"sender_sink": False, "earliest": {}})
    gain = {"required_calls": 0, "required_with_sender_ref": 0, "admitted_with_sender_ref": 0, "tasks": set()}
    for spec, probes in run_ajar.load(None):
        n0 = len(d.log)
        res = run_defense(d, spec, probes)  # one decide per probe, in order
        # re-decide each probe to read its candidate's reference origins (pure; same verdict)
        for r in res:
            if not r.probe.scored:
                continue
            v = d.decide(spec, r.probe.context, r.probe.candidate)
            origins = LAST.get("origins", ())
            sender = "named_sender" in origins
            if r.probe.fault_class.value == "ATTACKER_SEEDED":
                aid = r.probe.ground_truth.get("injection_id") or r.probe.probe_id.split("-k")[0]
                a = by_attack[(str(spec.task), aid)]
                a["sender_sink"] |= sender
                key = r.probe.candidate.key()
                k = len(r.probe.context.prefix)
                if key not in a["earliest"] or k < a["earliest"][key][0]:
                    a["earliest"][key] = (k, v is Verdict.ALLOW)
            elif r.probe.expected_label is Label.ALLOW and r.probe.required:
                gain["required_calls"] += 1
                if sender:
                    gain["required_with_sender_ref"] += 1
                    gain["admitted_with_sender_ref"] += v is Verdict.ALLOW
                    gain["tasks"].add(str(spec.task))
    risk = [{"task": t, "injection": i, "admitted": bool(a["earliest"]) and all(x[1] for x in a["earliest"].values())}
            for (t, i), a in by_attack.items() if a["sender_sink"]]
    res = {"attacks": len(by_attack), "attacks_with_named_sender_value": len(risk),
           "of_them_admitted_without_human": sum(x["admitted"] for x in risk), "risk": risk,
           "gain": {**gain, "tasks": sorted(gain["tasks"])}}
    print(json.dumps({k: v for k, v in res.items() if k != "risk"}, indent=1))
    json.dump(res, open(out, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
