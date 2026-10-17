"""Model-free re-run on kernel 618c4a9 + config_m1_c9v5 of:
 (a) Table 3 axor rows over ROPE's 52 tasks (banking,slack,travel; 369 attacks):
     no grants / L1+L2 / L1+L2+L4 oracle  -> OPL [CI], provisioned/52, attacks/369
 (b) Table 8 allowlist banking (3 rows): L1+L2 / L1+L2s / L1+L2s+L4 oracle.
Records kernel_commit + config_dir; compares to the paper's current numbers."""
import os, sys, json, subprocess
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ.pop("AXOR_HYP", None)
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AJAR_ROOT"] = "/home/user/Ajar"
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
import run_ajar  # noqa: E402
import paper_opl as P  # noqa: E402

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
CFG = "config_m1_c9v5"
data = run_ajar.load(None)


def filt(suites):
    s = set(suites.split(","))
    return [(sp, p) for sp, p in data if sp.task.suite in s]


def row(defense, subset):
    m = P.measure(defense, subset)
    return {"opl": m["opl"]["earliest"], "opl_any": m["opl"]["any"], "opl_all": m["opl"]["all"],
            "ci95_opl": m["ci95"]["opl"], "provisioned": m["provisioned"], "attacks": m["attacks"],
            "sufficiency": m["sufficiency"]}


def nogrants():
    return axor_ajar.AxorDefense("no-grants", integrity_default="context",
                                 integrity_origins="request-only", no_grants=True)


# ---- Table 3: ROPE 52 (banking,slack,travel) ----
t3set = filt("banking,slack,travel")
T3 = {
    "no grants": row(nogrants(), t3set),
    "L1+L2": row(P.make("grants:L1+L2s:R0"), t3set),
    "L1+L2+L4 oracle": row(P.make("grants:L1+L2s+L4:R0"), t3set),
}
# ---- Table 8: allowlist banking ----
t8set = filt("banking")
T8 = {
    "L1+L2": row(P.make("grants:L1+L2:R0"), t8set),
    "L1+L2s": row(P.make("grants:L1+L2s:R0"), t8set),
    "L1+L2s+L4 oracle": row(P.make("grants:L1+L2s+L4:R0"), t8set),
}

# paper's current numbers (for comparison)
PAPER_T3 = {  # final_numbers.md §2 rope table (kernel 09e98af, config_m1_c814)
    "no grants": {"opl": 0.0585, "ci95_opl": [0.0493, 0.0674], "provisioned": "23/52", "attacks": "0/369"},
    "L1+L2": {"opl": 0.0623, "ci95_opl": [0.0526, 0.0711], "provisioned": "27/52", "attacks": "1/369"},
    "L1+L2+L4 oracle": {"opl": 0.0623, "ci95_opl": [0.0526, 0.0711], "provisioned": "52/52", "attacks": "1/369"},
}
PAPER_T8 = {  # results/paper_opl-allowlist-banking.json (config not recorded)
    "L1+L2": {"opl": 0.6739, "ci95_opl": [0.6552, 0.6922], "provisioned": "5/11", "attacks": "112/144"},
    "L1+L2s": {"opl": 0.0519, "ci95_opl": [0.0362, 0.071], "provisioned": "5/11", "attacks": "0/144"},
    "L1+L2s+L4 oracle": {"opl": 0.0519, "ci95_opl": [0.0362, 0.071], "provisioned": "11/11", "attacks": "0/144"},
}


def diffs(new, paper):
    out = []
    for k in new:
        n, p = new[k], paper.get(k, {})
        for f in ("opl", "provisioned", "attacks"):
            if p.get(f) is not None and str(n[f]) != str(p[f]):
                out.append(f"{k}.{f}: rerun={n[f]} vs paper={p[f]}")
    return out


res = {"kernel_commit": KERNEL, "config_dir": CFG, "n_tasks_total": len(data),
       "table3_rope52": {"rerun": T3, "paper_current": PAPER_T3, "discrepancies": diffs(T3, PAPER_T3)},
       "table8_allowlist_banking": {"rerun": T8, "paper_current": PAPER_T8, "discrepancies": diffs(T8, PAPER_T8)}}
op = os.path.join(HERE, "results", "rerun_table3_8_c9v5.json")
json.dump(res, open(op, "w"), indent=1)
print("kernel", KERNEL, "config", CFG)
print("T3:", json.dumps(T3, indent=1))
print("T8:", json.dumps(T8, indent=1))
print("T3 discrepancies:", res["table3_rope52"]["discrepancies"])
print("T8 discrepancies:", res["table8_allowlist_banking"]["discrepancies"])
print("WROTE", op)
