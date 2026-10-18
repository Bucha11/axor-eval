"""Check 3: document-policy row for Table 2 (full 92), same format/seed/code as the oracle row.
grants:L1+L2s+L4 with confirm=document_injected (full document+message content INCLUDING injection).
f227951 + config_m1_c9v5, config-tuple, references on. No model (scripted confirmer)."""
import os, sys, json, subprocess, time
HERE = "/home/user/ajar-wt/experiments/ajar"
SC = "/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad"
WT = os.path.join(SC, "k_new")
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
GA = {s: dict(axor_ajar.load_config(s, "context", "request-only").grant_args) for s in ("banking", "slack", "travel", "workspace")}

t0 = time.time()
dfn = axor_ajar.grants_defense("grants:L1+L2s+L4:document_injected", "L1+L2s+L4", grant_args=GA, confirm="document_injected")
m = P.measure(dfn, data)
row = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v5", "path": "config-tuple, references on",
       "row": "axor, grants L1+L2s+L4 (document_injected = full doc/message content INCLUDING injection)",
       "bootstrap": "per-task, n=2000, seed=0 (paper_opl.bootstrap — same code/seed as all Table 2 rows)",
       "OPL": round(m["opl"]["earliest"], 4), "OPL_CI95": m["ci95"]["opl"],
       "sufficiency": m["sufficiency"], "sufficiency_CI95": m["ci95"]["sufficiency"],
       "provisioned": m["provisioned"], "attacks_admitted": m["attacks"],
       "seconds": round(time.time() - t0, 1)}
# oracle row for side-by-side (same run, cheap enough) — matches Table 2 c
dfo = axor_ajar.grants_defense("grants:L1+L2s+L4:oracle", "L1+L2s+L4", grant_args=GA, confirm="oracle")
mo = P.measure(dfo, data)
row["oracle_row_for_reference"] = {"OPL": round(mo["opl"]["earliest"], 4), "OPL_CI95": mo["ci95"]["opl"],
                                   "sufficiency": mo["sufficiency"], "sufficiency_CI95": mo["ci95"]["sufficiency"],
                                   "provisioned": mo["provisioned"], "attacks_admitted": mo["attacks"]}
op = os.path.join(HERE, "results", "docinj_table2_ci.json")
json.dump(row, open(op, "w"), indent=1, default=str)
print(json.dumps(row, indent=1, default=str))
print("WROTE", op)
