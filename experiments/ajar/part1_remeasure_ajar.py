"""Part 1 re-measurement on the FIXED kernel (claude/ns-field-fix-c9v5 = f227951) + config_m1_c9v5,
config-tuple path (GRANT_ARGS_FROM_CONFIG=1, L2=tuple), references on. No model.

Table 2 (full 97 tasks), Table 3 (rope52: L1+L2, L1+L2+L4 oracle), Table 8 (banking: origin / without
/ with-US133-in-O). OPL [95% CI], provisioned, attacks, sufficiency. Old numbers (618c4a9) inline for
the diff; the kernel_commit recorded is the fixed one."""
import os, sys, json, subprocess, dataclasses
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


def filt(suites):
    s = set(suites.split(","))
    return [(sp, p) for sp, p in data if sp.task.suite in s]


def row(defense, subset, dec=4):
    m = P.measure(defense, subset)
    return {"opl": round(m["opl"]["earliest"], dec), "ci95_opl": m["ci95"]["opl"],
            "provisioned": m["provisioned"], "attacks": m["attacks"], "sufficiency": m["sufficiency"]}


def nogrants():
    return axor_ajar.AxorDefense("origin", integrity_default="context", integrity_origins="request-only", no_grants=True)


full = data
rope = filt("banking,slack,travel")
bank = filt("banking")
res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5",
       "path": "GRANT_ARGS_FROM_CONFIG=1 + L2=tuple, references on"}

res["table2_full_L1+L2"] = {"new": row(P.make("grants:L1+L2s:R0"), full),
                            "old_618c4a9": {"opl": 0.0660, "provisioned": "61/92", "attacks": "1/609"}}
res["table3_rope52"] = {
    "L1+L2": {"new": row(P.make("grants:L1+L2s:R0"), rope),
              "old_618c4a9": {"opl": 0.0637, "provisioned": "30/52", "attacks": "1/369"}},
    "L1+L2+L4_oracle": {"new": row(P.make("grants:L1+L2s+L4:R0"), rope),
                        "old_618c4a9": {"opl": 0.0637, "provisioned": "52/52", "attacks": "1/369"}}}
t8 = {}
ADD["on"] = False
t8["origin_no_grants"] = {"new": row(nogrants(), bank), "old_618c4a9": {"opl": 0.0402}}
t8["without_US133_L1+L2"] = {"new": row(P.make("grants:L1+L2s:R0"), bank), "old_618c4a9": {"opl": 0.0602}}
ADD["on"] = True
t8["with_US133_in_O_L1+L2"] = {"new": row(P.make("grants:L1+L2s:R0"), bank), "old_618c4a9": {"opl": 0.2135}}
ADD["on"] = False
res["table8_banking"] = t8

op = os.path.join(HERE, "results", "part1_remeasure_ajar_nsfix.json")
json.dump(res, open(op, "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
print("WROTE", op)
