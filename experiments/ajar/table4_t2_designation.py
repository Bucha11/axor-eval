"""Part 1 (Table 4 denials, recorded trajs) + Part 2 (Ajar c9v5 L1+L2 provisioned tasks that
depend on a slack channel-NAME designation; recompute provisioned without them).
618c4a9 + config_m1_c9v5, config-grant path. NO model calls."""
import os, sys, json, glob, re
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"; os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo"); os.environ.pop("AXOR_HYP", None)
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar, run_ajar, paper_opl as P  # noqa: E402
from ajar.core.types import Label, Verdict  # noqa: E402

# ---------- Part 1: Table 4 denials from recorded trajs ----------
part1 = json.load(open("/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad/t4_denials.json"))

# ---------- Part 2: Ajar provisioned & channel-name designation ----------
data = run_ajar.load(None)
D = P.make("grants:L1+L2s:R0")
NAME_RE = re.compile(r"starting with|named|called|the .+ channel|#|'[^']+'", re.I)
PROP_RE = re.compile(r"smallest|largest|most|least|fewest|number of|recent|newest|oldest|active|member", re.I)
SLACK_CH_TOOLS = {"send_channel_message", "add_user_to_channel", "remove_user_from_channel", "invite_user_to_channel"}


def decide_desc(spec, ctx, cand):
    g = D.governor(spec)
    for call, out in axor_ajar.PREFIXES.outputs(spec, ctx):
        d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
        if getattr(d, "grant_id", None) is not None:
            k = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
            if k is not None:
                g.grant_store.commit(k)
        if out is not None:
            axor_ajar.present(g, d, out, call.tool, dict(call.args))
    d = g.evaluate(cand.tool, axor_ajar.agent_args(g, dict(cand.args)))
    return bool(d.allowed), d.category, getattr(d, "grant_source", None), getattr(d, "description", None)


prov_tasks, prov_full, prov_rope = [], 0, 0
name_dep_full, name_dep_rope = [], []
ROPE = {"banking", "slack", "travel"}
for spec, probes in data:
    if not spec.is_gradeable:
        continue
    req = [p for p in probes if p.scored and p.expected_label is Label.ALLOW and p.required]
    if not req:
        provisioned = True; admit_desc = []
    else:
        provisioned = True; admit_desc = []
        for p in req:
            allowed, cat, gs, desc = decide_desc(spec, p.context, p.candidate)
            if not allowed:
                provisioned = False
            elif desc and p.candidate.tool in SLACK_CH_TOOLS:
                admit_desc.append((p.candidate.tool, desc))
    if not provisioned:
        continue
    prov_full += 1
    if spec.task.suite in ROPE:
        prov_rope += 1
    # channel-NAME designation dependence (slack)
    name_descs = [(t, d) for (t, d) in admit_desc if NAME_RE.search(str(d)) and not PROP_RE.search(str(d))]
    if name_descs:
        rec = {"task": str(spec.task), "suite": spec.task.suite, "designations": [f"{t}: {d}" for t, d in name_descs]}
        name_dep_full.append(rec)
        if spec.task.suite in ROPE:
            name_dep_rope.append(rec)

part2 = {
    "provisioned_full": f"{prov_full}/92", "provisioned_rope52": f"{prov_rope}/52",
    "channel_name_designation_dependent_tasks_full": name_dep_full,
    "channel_name_designation_dependent_tasks_rope": [r["task"] for r in name_dep_rope],
    "provisioned_full_without_channel_name": f"{prov_full - len(name_dep_full)}/92",
    "provisioned_rope52_without_channel_name": f"{prov_rope - len(name_dep_rope)}/52",
}

out = {"kernel_commit": "618c4a9", "config_dir": "config_m1_c9v5",
       "grant_path": "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 + AXOR_AJAR_L2=tuple",
       "part1_table4_denials": part1, "part2_ajar_designation": part2}
op = os.path.join(HERE, "results", "table4_denials_and_designation_c9v5.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print("provisioned full", part2["provisioned_full"], "rope", part2["provisioned_rope52"])
print("channel-name-dependent full:", len(name_dep_full), "rope:", len(name_dep_rope))
for r in name_dep_full:
    print("  ", r["task"], r["designations"])
print("without name: full", part2["provisioned_full_without_channel_name"], "rope", part2["provisioned_rope52_without_channel_name"])
print("WROTE", op)
