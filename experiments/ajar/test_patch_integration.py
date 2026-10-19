"""NETWORK-FREE integration test: patched run_benign writes thinking metadata on success and,
on terminal API failure, marks api_error=True (NOT utility 0) and appends to the rerun list."""
import os, sys, json, glob, shutil, tempfile, urllib.error, io

SUITE = "banking"
os.environ["AXOR_BENCH_SUITE"] = SUITE
os.environ["AXOR_BENCH_BACKEND"] = "anthropic"
os.environ["AXOR_BENCH_MODEL"] = "claude-haiku-5-5"
os.environ["ANTHROPIC_API_KEY"] = "TEST-NO-NETWORK"
os.environ["AXOR_BENCH_CAMEL"] = "1"; os.environ["AXOR_BENCH_BENIGN_ONLY"] = "1"
os.environ["AXOR_BENCH_MAXTOK"] = "4096"; os.environ["AXOR_BENCH_BACKOFF"] = "0"
os.environ["AXOR_BENCH_GRANT_LEVELS"] = "L1"
os.environ["AXOR_BENCH_CONFIG"] = f"/home/user/ajar-wt/experiments/ajar/config_m1_c9v5/{SUITE}.yaml"
sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, "/home/user/ajar-wt/experiments/ajar")

import run_agentdojo as R  # noqa: E402
import agentdojo_adapter as A  # noqa: E402
import claude_harness_patch as P  # noqa: E402
P.apply()
from agentdojo.task_suite.load_suites import get_suites  # noqa: E402
suite = get_suites("v1")[SUITE]
ut = R.USER_TASKS[0]; R.USER_TASKS = [ut]

OK = [{"content": [{"type": "thinking", "thinking": "t"},
                   {"type": "tool_use", "id": "r0", "name": "get_balance", "input": {}}],
       "stop_reason": "tool_use", "usage": {"input_tokens": 500, "output_tokens": 100}},
      {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn",
       "usage": {"input_tokens": 60, "output_tokens": 8}}]


def _http_ok(self, body):
    n = sum(1 for m in body.get("messages", []) if m.get("role") == "assistant")
    return OK[min(n, 1)]


def _http_fail(self, body):
    raise urllib.error.HTTPError("u", 503, "err", {}, io.BytesIO(b"{}"))


out = {"suite": SUITE, "user_task": ut}

# Case A: success -> thinking metadata recorded
tdir = tempfile.mkdtemp(); os.environ["AXOR_BENCH_TRAJ_DIR"] = tdir
A.RawAnthropicLLM._http = _http_ok
utils, ex = R.run_benign(True, suite)
f = glob.glob(os.path.join(tdir, SUITE, "*.json"))
traj = json.load(open(f[0])) if f else {}
out["case_A_success"] = {"utils_counted": utils, "thinking": traj.get("thinking"),
                         "max_tokens": traj.get("max_tokens"), "api_error": traj.get("api_error"),
                         "thinking_blocks_seen": traj.get("thinking_blocks_seen"),
                         "pass": traj.get("thinking") == {"type": "adaptive"} and traj.get("max_tokens") == 4096
                                 and traj.get("api_error") is False and len(utils) == 1}

# Case B: terminal API failure -> api_error, NOT utility 0, task on rerun list
tdir2 = tempfile.mkdtemp(); os.environ["AXOR_BENCH_TRAJ_DIR"] = tdir2
rl = os.path.join(tempfile.mkdtemp(), "rerun.txt"); os.environ["AXOR_BENCH_RERUN_LIST"] = rl
os.environ["AXOR_BENCH_RETRIES"] = "3"
A.RawAnthropicLLM._http = _http_fail
utils2, ex2 = R.run_benign(True, suite)
f2 = glob.glob(os.path.join(tdir2, SUITE, "*.json"))
traj2 = json.load(open(f2[0])) if f2 else {}
rerun_tasks = [l.strip() for l in open(rl)] if os.path.exists(rl) else []
out["case_B_api_error"] = {"utils_counted": utils2, "utility_NOT_zero_counted": len(utils2) == 0,
                           "api_error_flag": traj2.get("api_error"), "trajectory_utility": traj2.get("utility"),
                           "rerun_list": rerun_tasks,
                           "note": "trajectory utility reads false (bool(None)); api_error=True gates it out of analysis",
                           "pass": len(utils2) == 0 and traj2.get("api_error") is True and ut in rerun_tasks}

out["ALL_PASS"] = out["case_A_success"]["pass"] and out["case_B_api_error"]["pass"]
print(json.dumps(out, indent=1, default=str))
json.dump(out, open("/home/user/ajar-wt/experiments/ajar/results/test_patch_integration.json", "w"), indent=1, default=str)
print("WROTE results/test_patch_integration.json")
