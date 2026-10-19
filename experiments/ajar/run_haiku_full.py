"""Full Haiku Table-4 run for ONE suite (AXOR_BENCH_SUITE): 4 conditions x 3 passes, OpenRouter
anthropic/claude-haiku-5.5, provider pinned Anthropic, reasoning {max_tokens:1024}, kernel f227951.
Shared spend ledger + cap. Inline stop-criteria abort. Resume via per-(cond,pass) TRAJ_DIR."""
import os, sys, json, glob

SUITE = os.environ["AXOR_BENCH_SUITE"]
KF = "/home/user/kf227951"
sys.path.insert(0, f"{KF}/examples/agentdojo")
sys.path.insert(0, "/home/user/ajar-wt/experiments/ajar")
ROOT = "/home/user/ajar-wt/experiments/ajar/results/haiku_full"
os.environ.setdefault("AXOR_BENCH_BACKEND", "openrouter")
os.environ.setdefault("AXOR_BENCH_MODEL", "anthropic/claude-haiku-5.5")
os.environ["AXOR_BENCH_CAMEL"] = "1"; os.environ["AXOR_BENCH_BENIGN_ONLY"] = "1"
os.environ["AXOR_BENCH_MAXTOK"] = "4096"; os.environ["AXOR_BENCH_THINKING"] = "1"
os.environ.pop("AXOR_BENCH_EFFORT", None)   # -> reasoning {max_tokens:1024}
os.environ["AXOR_BENCH_CONFIG"] = f"/home/user/ajar-wt/experiments/ajar/config_m1_c9v5/{SUITE}.yaml"
os.environ["AXOR_BENCH_SPEND_LOG"] = f"{ROOT}/spend.jsonl"
os.environ["AXOR_BENCH_SPEND_CAP"] = "5"
os.environ["AXOR_BENCH_RERUN_LIST"] = f"{ROOT}/rerun.txt"

import claude_harness_patch as P  # noqa: E402
import agentdojo_adapter as A  # noqa: E402
import run_agentdojo as R  # noqa: E402
P.apply()
from agentdojo.task_suite.load_suites import get_suites  # noqa: E402
suite = get_suites("v1")[SUITE]

COST_STOP = 4.0
CONDITIONS = [
    ("undefended", False, {"AXOR_BENCH_NO_GRANTS": "", "AXOR_BENCH_GRANT_LEVELS": "", "AXOR_BENCH_L4_CONFIRM": "oracle"}),
    ("origin", True, {"AXOR_BENCH_NO_GRANTS": "1", "AXOR_BENCH_GRANT_LEVELS": "", "AXOR_BENCH_L4_CONFIRM": "oracle"}),
    ("grants", True, {"AXOR_BENCH_NO_GRANTS": "", "AXOR_BENCH_GRANT_LEVELS": "L1", "AXOR_BENCH_L4_CONFIRM": "oracle",
                      "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG": "1", "AXOR_AJAR_L2": "tuple"}),
    ("grants_l4", True, {"AXOR_BENCH_NO_GRANTS": "", "AXOR_BENCH_GRANT_LEVELS": "L1+L2s+L4", "AXOR_BENCH_L4_CONFIRM": "view",
                         "AXOR_BENCH_L4_BUDGET": "5", "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG": "1", "AXOR_AJAR_L2": "tuple"})]


def spend_total():
    return A._spend_total()


def check_stop(tdir):
    """Scan freshly written trajectories for hard stop-criteria. Returns reason or None."""
    for p in glob.glob(os.path.join(tdir, SUITE, "*.json")):
        d = json.load(open(p))
        if d.get("truncated_max_tokens"):
            return f"max_tokens truncation in {d.get('user_task_id')}"
        pv = d.get("provider")
        if pv is not None and pv != "Anthropic":
            return f"provider {pv!r} != Anthropic in {d.get('user_task_id')}"
        kc = d.get("kernel_commit")
        if kc and not kc.startswith("f2279515"):
            return f"kernel {kc} != f227951 in {d.get('user_task_id')}"
    return None


log = []
aborted = None
for cond, governed, env in CONDITIONS:
    if aborted:
        break
    for pass_n in (1, 2, 3):
        for k in ("AXOR_BENCH_NO_GRANTS", "AXOR_BENCH_GRANT_LEVELS", "AXOR_BENCH_L4_CONFIRM",
                  "AXOR_BENCH_L4_BUDGET", "AXOR_AJAR_GRANT_ARGS_FROM_CONFIG", "AXOR_AJAR_L2"):
            os.environ.pop(k, None)
        os.environ.update(env)
        tdir = f"{ROOT}/{cond}/pass{pass_n}"
        os.environ["AXOR_BENCH_TRAJ_DIR"] = tdir
        if spend_total() > COST_STOP:
            aborted = f"cost ${spend_total():.4f} > ${COST_STOP}"; break
        try:
            utils, ex = R.run_benign(governed, suite)
        except A.SpendCapReached as e:
            aborted = f"spend cap: {e}"; break
        stop = check_stop(tdir)
        if stop:
            aborted = stop; break
        log.append({"cond": cond, "pass": pass_n, "n": len(utils), "util": sum(int(bool(u)) for u in utils),
                    "denied": getattr(ex, "denied_count", None),
                    "confirmations": sum((getattr(ex, "confirmations", {}) or {}).values()),
                    "cost_so_far": round(spend_total(), 4)})
        print(f"[{SUITE}] {cond} pass{pass_n}: util {log[-1]['util']}/{log[-1]['n']} "
              f"denied={log[-1]['denied']} conf={log[-1]['confirmations']} cost=${log[-1]['cost_so_far']}")

out = {"suite": SUITE, "aborted": aborted, "final_cost": round(spend_total(), 4), "log": log}
os.makedirs(f"{ROOT}/_driver", exist_ok=True)
json.dump(out, open(f"{ROOT}/_driver/{SUITE}.json", "w"), indent=1)
print(f"[{SUITE}] DONE aborted={aborted} cost=${out['final_cost']}")
if aborted:
    raise SystemExit(f"STOP ({SUITE}): {aborted}")
