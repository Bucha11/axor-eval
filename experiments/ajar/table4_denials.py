import json, glob, os
from collections import Counter, defaultdict
R = "/home/user/ajar-wt/experiments/ajar/results"
SUITES = ("banking", "slack", "travel", "workspace")
MODES = {"origin-only v2": ("live_origin_c9v5_v2", None),
         "A (grants L1+L2)": ("live_c9v5", "A"),
         "B (grants+L4 view)": ("live_c9v5", "B")}
BUCKET = {"taint_enforcement": "origin/taint", "audience_floor": "audience_floor",
          "reference_origin": "reference_origin", "reference_unknown": "reference_origin",
          "reference_secret": "reference_origin", "operator_set": "operator_set",
          "grant_gate": "grant_gate", "consequence_gate": "consequence/class"}
def bucket(c): return BUCKET.get(c, "other:" + str(c))

out = {}
for mode, (root, cfg) in MODES.items():
    base = os.path.join(R, root, cfg) if cfg else os.path.join(R, root)
    denied_by_suite = {s: Counter() for s in SUITES}
    failed_eps = {s: 0 for s in SUITES}
    failed_with_gate = {s: defaultdict(int) for s in SUITES}
    slack_fail_audience_web_send = 0
    for p in ("pass1", "pass2", "pass3"):
        for s in SUITES:
            for f in glob.glob(os.path.join(base, p, "traj", s, "user_task_*.json")):
                if s == "slack" and os.path.basename(f) == "user_task_4.json":
                    continue  # excluded everywhere
                d = json.load(open(f)); calls = d.get("calls") or []
                dn = [e for e in calls if not e.get("allowed")]
                for e in dn:
                    denied_by_suite[s][bucket(e.get("category"))] += 1
                if not d.get("utility"):
                    failed_eps[s] += 1
                    gates = {bucket(e.get("category")) for e in dn}
                    for g in gates:
                        failed_with_gate[s][g] += 1
                    if s == "slack":
                        if any(e.get("category") == "audience_floor" and
                               (e.get("tool") == "post_webpage" or str(e.get("tool", "")).startswith("send_"))
                               for e in dn):
                            slack_fail_audience_web_send += 1
    out[mode] = {
        "denied_calls_by_suite_gate": {s: dict(denied_by_suite[s]) for s in SUITES},
        "failed_episodes_by_suite": failed_eps,
        "failed_episodes_with_gate_by_suite": {s: dict(failed_with_gate[s]) for s in SUITES},
        "slack_failures_with_audience_floor_on_postwebpage_or_send": slack_fail_audience_web_send,
    }
json.dump(out, open("/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad/t4_denials.json", "w"), indent=1)
print(json.dumps(out, indent=1))
