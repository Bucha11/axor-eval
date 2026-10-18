"""Part 3: count admitted calls with grant_source=L1 AND description!=None (designation/pointer
grants) in Ajar Table 2 (required/unneeded), under one kernel (KERNEL_WT). config_m1_c9v5,
config-tuple, references on, b=grants:L1+L2s. No model. Also reads live_c9v5 A/B recorded counts."""
import os, sys, json, subprocess, glob
from collections import Counter
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"; os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")
import axor_ajar, run_ajar, paper_opl as P  # noqa: E402
from ajar.core.types import Label  # noqa: E402
KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
data = run_ajar.load(None)
D = P.make("grants:L1+L2s:R0")

req = Counter(); unn = Counter()          # all admitted by grant_source
req_desc = 0; unn_desc = 0                  # admitted with grant_source==L1 AND description!=None
desc_phrases = Counter()
for spec, probes in data:
    for p in probes:
        if not p.scored or p.expected_label is not Label.ALLOW:
            continue
        g = D.governor(spec)
        for call, out in axor_ajar.PREFIXES.outputs(spec, p.context):
            dd = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
            if getattr(dd, "grant_id", None) is not None:
                k = g.spend(dd, axor_ajar.spend_args(dd, dict(call.args)))
                if k is not None:
                    g.grant_store.commit(k)
            if out is not None:
                axor_ajar.present(g, dd, out, call.tool, dict(call.args))
        d = g.evaluate(p.candidate.tool, axor_ajar.agent_args(g, dict(p.candidate.args)))
        if not d.allowed:
            continue
        gs = str(getattr(d, "grant_source", None))
        desc = getattr(d, "description", None)
        (req if p.required else unn)[gs] += 1
        if gs == "L1" and desc is not None:
            if p.required:
                req_desc += 1
            else:
                unn_desc += 1
            desc_phrases[str(desc)[:60]] += 1

res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on, b=L1+L2s",
       "ajar_required_admitted_by_grant_source": dict(req),
       "ajar_unneeded_admitted_by_grant_source": dict(unn),
       "ajar_L1_with_description_required": req_desc,
       "ajar_L1_with_description_unneeded": unn_desc,
       "ajar_L1_with_description_total": req_desc + unn_desc,
       "top_description_phrases": dict(desc_phrases.most_common(20))}

# live A/B: recorded grant_source + description (cannot replay: args not stored in calls)
for mode in ("A", "B"):
    c = Counter(); n_l1desc = 0; phr = Counter()
    for pth in glob.glob(os.path.join(HERE, "results", "live_c9v5", mode, "pass*", "traj", "*", "user_task_*.json")):
        d = json.load(open(pth))
        for call in d.get("calls") or []:
            if not call.get("allowed"):
                continue
            gs = str(call.get("grant_source")); desc = call.get("description")
            c[gs] += 1
            if gs == "L1" and desc is not None:
                n_l1desc += 1; phr[str(desc)[:60]] += 1
    res[f"live_{mode}_admitted_by_grant_source_recorded"] = dict(c)
    res[f"live_{mode}_L1_with_description_recorded"] = n_l1desc
    res[f"live_{mode}_description_phrases"] = dict(phr.most_common(10))

op = os.path.join(HERE, "results", f"l1desc_count_{KERNEL}.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
