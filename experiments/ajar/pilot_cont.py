"""#1 pilot: GPT-4o, UNDEFENDED, banking, 16 user tasks x 3 continuation injections x 1 pass.
Spend cap $3 (harness-enforced). Per (user_task, injection) -> (utility, security). PAID."""
import os, sys, json
HERE = "/home/user/ajar-wt/experiments/ajar"
ADJ = "/home/user/core-m1/examples/agentdojo"
os.environ["AXOR_BENCH_SUITE"] = "banking"
os.environ["AXOR_BENCH_BACKEND"] = "openrouter"
os.environ["AXOR_BENCH_MODEL"] = "openai/gpt-4o"
os.environ["AXOR_BENCH_MAXTOK"] = "1024"
os.environ["AXOR_BENCH_ALL_USER_TASKS"] = "1"           # all 16 banking user tasks
os.environ["AXOR_BENCH_INJECTIONS"] = "injection_task_9,injection_task_10,injection_task_11"
os.environ["AXOR_BENCH_ATTACK"] = "important_instructions"
ROOT = os.path.join(HERE, "results", "cont_pilot_gpt4o")
os.makedirs(ROOT, exist_ok=True)
os.environ["AXOR_BENCH_SPEND_LOG"] = os.path.join(ROOT, "spend.jsonl")
os.environ["AXOR_BENCH_SPEND_CAP"] = "3"
os.environ["AXOR_BENCH_TRAJ_DIR"] = os.path.join(ROOT, "traj")
sys.path.insert(0, ADJ); sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import run_agentdojo as R
from agentdojo_adapter import SpendCapReached
suite = R.get_suites("v1")["banking"]
import banking_cont_inject as B
B.register(suite)

pipeline, _ = R.build_pipeline(False)          # undefended
attack = R.load_attack(R.ATTACK, suite, pipeline)
rows = []
stop = False
for ut_id in R.USER_TASKS:
    if stop: break
    ut = suite.get_user_task_by_id(ut_id)
    for it_id in R.INJECTION_TASKS:
        it = suite.get_injection_task_by_id(it_id)
        injections = attack.attack(ut, it)
        try:
            utility, security = suite.run_task_with_pipeline(pipeline, ut, it, injections)
        except SpendCapReached as e:
            print("SPEND CAP:", e); stop = True; break
        except Exception as e:
            print(f"  {ut_id} x {it_id}: ERROR {type(e).__name__}: {e}")
            rows.append({"user_task": ut_id, "injection": it_id, "error": f"{type(e).__name__}: {e}"}); continue
        rows.append({"user_task": ut_id, "injection": it_id, "utility": bool(utility), "attack_landed": bool(security)})
        print(f"  {ut_id:<13} x {it_id:<18} utility={'Y' if utility else 'n'} attack_landed={'Y' if security else 'n'}")

landed = sum(1 for r in rows if r.get("attack_landed"))
by_inj = {}
for r in rows:
    if "attack_landed" in r:
        by_inj.setdefault(r["injection"], [0, 0]); by_inj[r["injection"]][0] += int(r["attack_landed"]); by_inj[r["injection"]][1] += 1
spend = sum(json.loads(l).get("cost") or 0 for l in open(os.environ["AXOR_BENCH_SPEND_LOG"])) if os.path.exists(os.environ["AXOR_BENCH_SPEND_LOG"]) else 0.0
out = {"mode": "undefended", "model": "openai/gpt-4o", "suite": "banking",
       "pairs": len([r for r in rows if "attack_landed" in r]), "attacks_landed": landed,
       "by_injection": {k: {"landed": v[0], "pairs": v[1]} for k, v in by_inj.items()},
       "spend_usd": round(spend, 4), "stopped_by_cap": stop, "rows": rows}
json.dump(out, open(os.path.join(ROOT, "pilot_result.json"), "w"), indent=2)
print(f"\nPILOT: landed {landed}/{out['pairs']}  by_injection={out['by_injection']}  spend ${spend:.4f}")
print("DONE", os.path.join(ROOT, "pilot_result.json"))
