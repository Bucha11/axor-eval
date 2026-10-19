"""AFTER the (paid) calibration run, compare ACTUAL Claude tokens/call against the o4-mini x1.15
estimate and reproject the full-run cost with the realized multiplier. Reads the calibration
spend ledger + trajectory dir. NO API CALLS (pure analysis of saved calibration output).

Usage:
  python calib_compare.py <calib_spend.jsonl> <calib_traj_dir> [model]
"""
import sys, json, glob, os, statistics as st

SPEND = sys.argv[1] if len(sys.argv) > 1 else "results/claude_calib/spend.jsonl"
TRAJ = sys.argv[2] if len(sys.argv) > 2 else "results/claude_calib/traj"
MODEL = sys.argv[3] if len(sys.argv) > 3 else "claude-haiku-5-5"
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}

# o4-mini banking L1+L2 baseline (per-call means, from live_v5/spend.jsonl overall) and the
# assumption the estimate used:
O4_IN_MEAN, O4_OUT_MEAN = 2302, 558
ASSUMED_MULT = 1.15
# full-run token totals (o4-mini, 4 conditions x 3 passes), from cost_estimate_claude.json:
FULL_IN_O4 = (3141750 + 3289976 + 3141750 + 3339145)   # 12.91M  (3-pass, all 4 conditions)
FULL_OUT_O4 = (761813 + 696119 + 761813 + 712618)        # 2.93M

ins, outs, costs = [], [], 0.0
for ln in open(SPEND):
    ln = ln.strip()
    if not ln:
        continue
    d = json.loads(ln)
    ins.append(d.get("prompt_tokens") or 0); outs.append(d.get("completion_tokens") or 0)
    costs += d.get("cost") or 0.0
ncalls = len(ins)
tasks = glob.glob(os.path.join(TRAJ, "*", "*.json")) or glob.glob(os.path.join(TRAJ, "*.json"))

act_in, act_out = (st.mean(ins) if ins else 0), (st.mean(outs) if outs else 0)
mult_in = act_in / O4_IN_MEAN if act_in else None
mult_out = act_out / O4_OUT_MEAN if act_out else None

pin, pout = PRICE[MODEL]
# reproject full run with the REALIZED per-token multiplier (replaces x1.15)
def proj(passes, mi, mo):
    tin = FULL_IN_O4 / 3 * passes * mi
    tout = FULL_OUT_O4 / 3 * passes * mo
    return round(tin / 1e6 * pin + tout / 1e6 * pout, 2)

out = {"model": MODEL, "calib_calls": ncalls, "calib_tasks": len(tasks),
       "calib_cost_$": round(costs, 4),
       "actual_tokens_per_call": {"in_mean": round(act_in), "out_mean": round(act_out)},
       "o4mini_baseline_per_call": {"in_mean": O4_IN_MEAN, "out_mean": O4_OUT_MEAN},
       "realized_multiplier": {"input": round(mult_in, 3) if mult_in else None,
                               "output": round(mult_out, 3) if mult_out else None,
                               "assumed_was": ASSUMED_MULT},
       "calls_per_task_actual": round(ncalls / len(tasks), 2) if tasks else None,
       "full_run_4cond_reprojected_$": {
           f"{p}pass": proj(p, mult_in or ASSUMED_MULT, mult_out or ASSUMED_MULT) for p in (1, 2, 3)},
       "verdict": None}
mi, mo = (mult_in or ASSUMED_MULT), (mult_out or ASSUMED_MULT)
out["verdict"] = ("estimate CONSERVATIVE (realized < 1.15)" if max(mi, mo) <= ASSUMED_MULT
                  else f"estimate LOW — realized in x{mi:.2f}/out x{mo:.2f} exceed x{ASSUMED_MULT}; "
                       "scale the cost table up accordingly before the full run")
print(json.dumps(out, indent=1))
json.dump(out, open("results/calib_compare_out.json", "w"), indent=1)
