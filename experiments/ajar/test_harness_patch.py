"""NETWORK-FREE test of claude_harness_patch: retry->success, terminal->ApiError (rerun,
not utility 0), spend cap fires, thinking+tool_use parse. No paid calls."""
import os, sys, json, tempfile, urllib.error, io

sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, "/home/user/ajar-wt/experiments/ajar")
os.environ["AXOR_BENCH_BACKEND"] = "anthropic"
os.environ["AXOR_BENCH_MODEL"] = "claude-haiku-5-5"
os.environ["ANTHROPIC_API_KEY"] = "TEST-NO-NETWORK"
os.environ["AXOR_BENCH_BACKOFF"] = "0"          # no real sleeping in the test
os.environ["AXOR_BENCH_RETRIES"] = "5"
os.environ["AXOR_BENCH_MAXTOK"] = "4096"

import claude_harness_patch as P  # noqa: E402
import agentdojo_adapter as A  # noqa: E402
P.apply()

results = {}


class _FakeFn:
    name = "get_balance"; description = "read"
    class parameters:  # noqa: N801
        @staticmethod
        def model_json_schema():
            return {"type": "object", "properties": {}, "required": []}


class _FakeRuntime:
    functions = {"get_balance": _FakeFn()}


USER_MSG = [{"role": "user", "content": [{"type": "text", "content": "pay rent"}]}]
OK_TOOLUSE = {"content": [{"type": "thinking", "thinking": "let me think"},
                          {"type": "text", "text": "ok"},
                          {"type": "tool_use", "id": "t1", "name": "get_balance", "input": {}}],
              "stop_reason": "tool_use", "usage": {"input_tokens": 1000, "output_tokens": 300}}


def _httperror(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"{}"))


# ── Test 1: retry -> success (2x 503 then ok) ───────────────────────────────────
def make_flaky(fail_n, code=503):
    state = {"n": 0}
    def _http(self, body):
        if state["n"] < fail_n:
            state["n"] += 1
            raise _httperror(code)
        return OK_TOOLUSE
    return _http

llm = A.RawAnthropicLLM(model="claude-haiku-5-5", max_tokens=4096)
A.RawAnthropicLLM._http = make_flaky(2)
os.environ.pop("AXOR_BENCH_SPEND_LOG", None)
out = llm.query("q", _FakeRuntime(), messages=USER_MSG)
asst = out[3][-1]
results["t1_retry_then_success"] = {
    "retries": llm._retries, "expected_retries": 2,
    "tool_calls_parsed": len(asst["tool_calls"] or []),
    "thinking_blocks_seen": llm.last_thinking_blocks,
    "pass": llm._retries == 2 and len(asst["tool_calls"] or []) == 1 and llm.last_thinking_blocks == 1}

# ── Test 2: terminal failure -> ApiError ────────────────────────────────────────
llm2 = A.RawAnthropicLLM(model="claude-haiku-5-5", max_tokens=4096)
A.RawAnthropicLLM._http = make_flaky(99)   # always fails
raised = None
try:
    llm2.query("q", _FakeRuntime(), messages=USER_MSG)
except P.ApiError as e:
    raised = str(e)
results["t2_terminal_ApiError"] = {"raised_ApiError": raised is not None,
                                   "attempts_made": llm2._retries + 1, "expected_attempts": 5,
                                   "msg": raised, "pass": raised is not None and llm2._retries == 4}

# ── Test 3: spend cap fires before the call ─────────────────────────────────────
tmp = tempfile.mkdtemp()
log = os.path.join(tmp, "spend.jsonl")
open(log, "w").write(json.dumps({"model": "x", "cost": 5.0}) + "\n")   # already $5 spent
os.environ["AXOR_BENCH_SPEND_LOG"] = log
os.environ["AXOR_BENCH_SPEND_CAP"] = "1"     # cap $1 < $5 spent
A.RawAnthropicLLM._http = make_flaky(0)      # would succeed, but guard must fire first
llm3 = A.RawAnthropicLLM(model="claude-haiku-5-5", max_tokens=4096)
capped = False
try:
    llm3.query("q", _FakeRuntime(), messages=USER_MSG)
except A.SpendCapReached:
    capped = True
results["t3_spend_cap_fires"] = {"capped": capped, "pass": capped}

# ── Test 4: usage logged -> cap works for Anthropic (cost computed & written) ────
log2 = os.path.join(tmp, "spend2.jsonl")
os.environ["AXOR_BENCH_SPEND_LOG"] = log2
os.environ.pop("AXOR_BENCH_SPEND_CAP", None)
A.RawAnthropicLLM._http = make_flaky(0)
llm4 = A.RawAnthropicLLM(model="claude-haiku-5-5", max_tokens=4096)
llm4.query("q", _FakeRuntime(), messages=USER_MSG)
lines = [json.loads(l) for l in open(log2)]
exp_cost = 1000 / 1e6 * 0.10 + 300 / 1e6 * 0.50   # haiku-5-5 rate
results["t4_usage_logged"] = {"spend_lines": len(lines), "cost_written": lines[0]["cost"] if lines else None,
                              "expected_cost": round(exp_cost, 8),
                              "thinking_cfg_sent": llm4.think_cfg,
                              "pass": bool(lines) and abs(lines[0]["cost"] - exp_cost) < 1e-9 and llm4.think_cfg == {"type": "adaptive"}}

results["ALL_PASS"] = all(v["pass"] for k, v in results.items() if isinstance(v, dict) and "pass" in v)
print(json.dumps(results, indent=1, default=str))
json.dump(results, open("/home/user/ajar-wt/experiments/ajar/results/test_harness_patch.json", "w"), indent=1, default=str)
print("WROTE results/test_harness_patch.json")
