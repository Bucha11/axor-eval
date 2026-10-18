"""Ajar battery on one kernel (KERNEL_WT) + config_m1_c9v5, config-tuple path, references on. No model.
Table 2 (full 97): a=origin-only, b=L1+L2s tuple, c-oracle=L1+L2s+L4 oracle.
Table 3 (rope52 banking,slack,travel): a/b/c. Table 8 (banking): origin/without/with-US133.
grants-vs-origin probe deltas (required/unneeded admits under a vs b)."""
import os, sys, json, subprocess, dataclasses
from collections import Counter
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, os.environ.get("CFG", "config_m1_c9v5"))
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
US133 = "US133000000121212121212"
_orig = axor_ajar.load_config
ADD = {"on": False}


def _patched(s, i, io):
    c = _orig(s, i, io)
    if ADD["on"] and s == "banking":
        osv = {t: {a: list(v) for a, v in ar.items()} for t, ar in c.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osv and "recipient" in osv[t] and US133 not in osv[t]["recipient"]:
                osv[t]["recipient"].append(US133)
        c = dataclasses.replace(c, operator_sets=osv)
    return c


axor_ajar.load_config = _patched


def filt(s):
    ss = set(s.split(","))
    return [(sp, p) for sp, p in data if sp.task.suite in ss]


def nogrants():
    return axor_ajar.AxorDefense("origin", integrity_default="context", integrity_origins="request-only", no_grants=True)


def full_row(defense, subset):
    m = P.measure(defense, subset)
    return {"opl": round(m["opl"]["earliest"], 4), "ci95_opl": m["ci95"]["opl"],
            "sufficiency": m["sufficiency"], "ci95_suff": m["ci95"]["sufficiency"],
            "provisioned": m["provisioned"], "attacks": m["attacks"]}


full = data; rope = filt("banking,slack,travel"); bank = filt("banking")
res = {"kernel_commit": KERNEL, "config_dir": os.environ["AXOR_AJAR_CONFIG_DIR"].split("/")[-1],
       "path": "GRANT_ARGS_FROM_CONFIG=1 + L2=tuple, references on"}
res["table2_full"] = {
    "a_origin": full_row(nogrants(), full),
    "b_L1+L2s": full_row(P.make("grants:L1+L2s:R0"), full),
    "c_oracle": full_row(P.make("grants:L1+L2s+L4:R0"), full)}
res["table3_rope52"] = {
    "a_origin": full_row(nogrants(), rope),
    "b_L1+L2s": full_row(P.make("grants:L1+L2s:R0"), rope),
    "c_oracle": full_row(P.make("grants:L1+L2s+L4:R0"), rope)}
t8 = {}
ADD["on"] = False
t8["origin"] = full_row(nogrants(), bank)
t8["without_US133"] = full_row(P.make("grants:L1+L2s:R0"), bank)
ADD["on"] = True
t8["with_US133_in_O"] = full_row(P.make("grants:L1+L2s:R0"), bank)
ADD["on"] = False
res["table8_banking"] = t8

# grants-vs-origin probe deltas (admissible UNDER_GRANT probes: required / unneeded admits under a vs b)
from ajar.runner import run_defense  # noqa: E402
from ajar.core.types import Verdict, FaultClass  # noqa: E402
a_def = nogrants(); b_def = P.make("grants:L1+L2s:R0")


def admits(defense):
    req = unn = 0
    radm = Counter(); uadm = Counter()
    for spec, probes in data:
        res_ = run_defense(defense, spec, probes)
        for r in res_:
            p = r.probe
            if not p.scored or p.expected_label is not Label.ALLOW:
                continue
            if p.fault_class is not FaultClass.UNDER_GRANT:
                continue
            allow = r.verdict is Verdict.ALLOW
            if p.required:
                req += int(allow)
            else:
                unn += int(allow)
    return req, unn


ar, au = admits(a_def); br, bu = admits(b_def)
res["grants_vs_origin"] = {"required_a_admits": ar, "required_b_admits": br,
                           "unneeded_a_admits": au, "unneeded_b_admits": bu,
                           "old_618c4a9": {"required": "a 296 / b 299", "unneeded": "a 974 / b 969"}}
op = os.path.join(HERE, "results", f"remeasure_ajar_{KERNEL}.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
