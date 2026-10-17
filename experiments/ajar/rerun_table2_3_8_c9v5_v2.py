"""Corrected re-run (kernel 618c4a9 + config_m1_c9v5), model-free. The grants arm uses the
SAME path as the paper's Table 2/3 (config driving args as grant args + kernel L2 tuple
templates: AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1, AXOR_AJAR_L2=tuple), NOT the derive-R0 table.
 1. Table 2 (full 97 tasks / 609 attacks): L1+L2 -> compare 0.0660 [0.0594,0.0721] 61/92 1/609.
 2. Table 3 (rope52 banking,slack,travel): L1+L2, L1+L2+L4 oracle.
 3. Table 8 (banking): origin (no grants); with-IBAN (US133 added to banking operator_set);
    without (plain c9v5). OPL to 4 decimals.
Records kernel_commit + config in JSON."""
import os, sys, json, subprocess, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
# the paper's Table 2/3 grants path:
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"
os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
import run_ajar  # noqa: E402
import paper_opl as P  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
data = run_ajar.load(None)
US133 = "US133000000121212121212"
_orig_load = axor_ajar.load_config
_ADD_US133 = {"on": False}


def _patched_load(suite, integrity_default, integrity_origins):
    cfg = _orig_load(suite, integrity_default, integrity_origins)
    if _ADD_US133["on"] and suite == "banking":
        osets = {t: {a: list(vs) for a, vs in args.items()} for t, args in cfg.operator_sets.items()}
        for t in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
            if t in osets and "recipient" in osets[t] and US133 not in osets[t]["recipient"]:
                osets[t]["recipient"].append(US133)
        cfg = dataclasses.replace(cfg, operator_sets=osets)
    return cfg


axor_ajar.load_config = _patched_load


def filt(suites):
    s = set(suites.split(","))
    return [(sp, p) for sp, p in data if sp.task.suite in s]


def row(defense, subset, dec=4):
    m = P.measure(defense, subset)
    return {"opl": round(m["opl"]["earliest"], dec), "ci95_opl": m["ci95"]["opl"],
            "provisioned": m["provisioned"], "attacks": m["attacks"], "sufficiency": m["sufficiency"]}


def nogrants():
    return axor_ajar.AxorDefense("origin", integrity_default="context",
                                 integrity_origins="request-only", no_grants=True)


# L1+L2 and L1+L2+L4 via config-grant path (env set above; make(...:R0) table is overridden by the env)
full = data
rope = filt("banking,slack,travel")
bank = filt("banking")

res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "grant_path": "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 + AXOR_AJAR_L2=tuple",
       "n_tasks_total": len(data)}

# 1. Table 2 full
res["table2_full"] = {"L1+L2": row(P.make("grants:L1+L2s:R0"), full),
                      "paper": {"opl": 0.0660, "ci95_opl": [0.0594, 0.0721], "provisioned": "61/92", "attacks": "1/609"}}
# 2. Table 3 rope52
res["table3_rope52"] = {"L1+L2": row(P.make("grants:L1+L2s:R0"), rope),
                        "L1+L2+L4 oracle": row(P.make("grants:L1+L2s+L4:R0"), rope),
                        "paper": {"L1+L2": {"opl": 0.0637, "provisioned": "30/52", "attacks": "1/369"},
                                  "L1+L2+L4 oracle": {"opl": 0.0637, "provisioned": "52/52", "attacks": "1/369"}}}
# 3. Table 8 banking
t8 = {}
t8["origin (no grants)"] = row(nogrants(), bank)
t8["without IBAN (L1+L2)"] = row(P.make("grants:L1+L2s:R0"), bank)
_ADD_US133["on"] = True
t8["with IBAN (L1+L2, US133 in O)"] = row(P.make("grants:L1+L2s:R0"), bank)
_ADD_US133["on"] = False
res["table8_banking"] = {**t8, "paper": {"origin": {"opl": 0.040, "attacks": "0"},
                                         "with_IBAN": {"opl": 0.595, "attacks": "80"},
                                         "without": {"opl": 0.060, "attacks": "0"}}}

op = os.path.join(HERE, "results", "rerun_table2_3_8_c9v5_v2.json")
json.dump(res, open(op, "w"), indent=1)
print("kernel", KERNEL)
print(json.dumps({k: v for k, v in res.items() if k.startswith("table")}, indent=1))
print("WROTE", op)
