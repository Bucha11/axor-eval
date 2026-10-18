"""Part 2 (count grant_source=L2) + Part 3 (document_injected). f227951 + config_m1_c9v5,
config-tuple, references on. No model."""
import os, sys, json, subprocess, glob
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
GA = {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args) for s in ("banking", "slack", "travel", "workspace")}
D = P.make("grants:L1+L2s:R0")

# ---- Part 2: grant_source=L2 count in Ajar Table 2 (required/unneeded admitted) ----
from collections import Counter
src_req = Counter(); src_unn = Counter()
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
        if d.allowed:
            gs = str(getattr(d, "grant_source", None))
            (src_req if p.required else src_unn)[gs] += 1
part2 = {"ajar_required_admitted_by_grant_source": dict(src_req),
         "ajar_unneeded_admitted_by_grant_source": dict(src_unn),
         "ajar_L2_count": src_req.get("L2", 0) + src_unn.get("L2", 0)}

# live A/B grant_source from recorded trajectories
for mode in ("A", "B"):
    c = Counter()
    for pth in glob.glob(os.path.join(HERE, "results", "live_c9v5", mode, "pass*", "traj", "*", "user_task_*.json")):
        d = json.load(open(pth))
        for call in d.get("calls") or []:
            if call.get("allowed"):
                c[str(call.get("grant_source"))] += 1
    part2[f"live_{mode}_admitted_by_grant_source"] = dict(c)
    part2[f"live_{mode}_L2_count"] = c.get("L2", 0)

# ---- Part 3: document_injected (Ajar) ----
def row(defense):
    m = P.measure(defense, data)
    return {"opl": round(m["opl"]["earliest"], 4), "sufficiency": m["sufficiency"], "provisioned": m["provisioned"], "attacks": m["attacks"]}

def dfn(confirm):
    return axor_ajar.grants_defense(f"grants:L1+L2s+L4:{confirm}", "L1+L2s+L4", grant_args=GA, confirm=confirm)

part3 = {"document_clean": row(dfn("document")), "document_injected": row(dfn("document_injected")),
         "view_ref": row(dfn("view")), "oracle_ref": row(dfn("oracle"))}

out = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on",
       "part2_L2_counts": part2, "part3_document_injected_ajar": part3}
op = os.path.join(HERE, "results", "l2count_docinj_nsfix.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
print("WROTE", op)
