"""NETWORK-FREE test of the OpenRouter path in claude_harness_patch: reasoning+tool_calls parse,
provider/truncated/reasoning metadata, provider pin in request, api_error, spend cap. No paid calls."""
import os, sys, json, tempfile

KF = "/home/user/kf227951"
sys.path.insert(0, f"{KF}/examples/agentdojo")
sys.path.insert(0, "/home/user/ajar-wt/experiments/ajar")
os.environ["AXOR_BENCH_BACKEND"] = "openrouter"
os.environ["AXOR_BENCH_MODEL"] = "anthropic/claude-haiku-5.5"
os.environ["OPEN_ROUTER_API_KEY"] = "TEST-NO-NETWORK"
os.environ["AXOR_BENCH_THINKING"] = "1"; os.environ["AXOR_BENCH_MAXTOK"] = "4096"
os.environ.pop("AXOR_BENCH_EFFORT", None)        # -> reasoning max_tokens=1024 default

import claude_harness_patch as P  # noqa: E402
import agentdojo_adapter as A  # noqa: E402
P.apply()
R = {}


class _FakeFn:
    name = "send_money"; description = "pay"
    class parameters:  # noqa: N801
        @staticmethod
        def model_json_schema():
            return {"type": "object", "properties": {"recipient": {"type": "string"}}, "required": ["recipient"]}


class _FakeRuntime:
    functions = {"send_money": _FakeFn()}


USER = [{"role": "user", "content": [{"type": "text", "content": "pay rent to DE_user"}]}]


def or_resp(finish="tool_use", provider="Anthropic"):
    return {"provider": provider,
            "choices": [{"finish_reason": finish,
                         "message": {"content": "paying",
                                     "reasoning_details": [{"type": "reasoning.text", "text": "think"}],
                                     "tool_calls": [{"id": "c1", "type": "function",
                                                     "function": {"name": "send_money",
                                                                  "arguments": json.dumps({"recipient": "DE_user"})}}]}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 400,
                      "completion_tokens_details": {"reasoning_tokens": 256}, "cost": 0.00032}}


# Test 1: parse + metadata + request shape ---------------------------------------
captured = {}
def _post_ok(self, body):
    captured.update(body)
    return or_resp()
A.OpenRouterLLM._post = _post_ok
os.environ.pop("AXOR_BENCH_SPEND_LOG", None)
llm = A.OpenRouterLLM(model="anthropic/claude-haiku-5.5", max_tokens=4096)
out = llm.query("q", _FakeRuntime(), messages=USER)
asst = out[3][-1]
R["t1_parse_meta"] = {
    "tool_calls": len(asst["tool_calls"] or []), "provider": llm.last_provider,
    "thinking_blocks": llm.last_thinking_blocks, "truncated": llm.last_truncated,
    "reasoning_sent": captured.get("reasoning"), "provider_pin": captured.get("provider"),
    "pass": (len(asst["tool_calls"] or []) == 1 and llm.last_provider == "Anthropic"
             and llm.last_thinking_blocks == 1 and llm.last_truncated is False
             and captured.get("reasoning") == {"max_tokens": 1024}
             and captured.get("provider") == {"order": ["anthropic"], "allow_fallbacks": False})}

# Test 2: truncated (finish_reason length) ---------------------------------------
A.OpenRouterLLM._post = lambda self, body: or_resp(finish="length")
llm2 = A.OpenRouterLLM(model="anthropic/claude-haiku-5.5", max_tokens=4096)
llm2.query("q", _FakeRuntime(), messages=USER)
R["t2_truncated"] = {"truncated": llm2.last_truncated, "pass": llm2.last_truncated is True}

# Test 3: terminal failure -> ApiError -------------------------------------------
def _post_fail(self, body):
    raise RuntimeError("OpenRouter 503: upstream")
A.OpenRouterLLM._post = _post_fail
llm3 = A.OpenRouterLLM(model="anthropic/claude-haiku-5.5", max_tokens=4096)
raised = None
try:
    llm3.query("q", _FakeRuntime(), messages=USER)
except P.ApiError as e:
    raised = str(e)
R["t3_terminal_ApiError"] = {"raised": raised, "pass": raised is not None}

# Test 4: spend cap fires --------------------------------------------------------
tmp = tempfile.mkdtemp(); log = os.path.join(tmp, "s.jsonl")
open(log, "w").write(json.dumps({"cost": 5.0}) + "\n")
os.environ["AXOR_BENCH_SPEND_LOG"] = log; os.environ["AXOR_BENCH_SPEND_CAP"] = "1"
A.OpenRouterLLM._post = _post_ok
llm4 = A.OpenRouterLLM(model="anthropic/claude-haiku-5.5", max_tokens=4096)
capped = False
try:
    llm4.query("q", _FakeRuntime(), messages=USER)
except A.SpendCapReached:
    capped = True
R["t4_spend_cap"] = {"capped": capped, "pass": capped}

# Test 5: provider stop-criterion detectable (non-Anthropic provider) ------------
os.environ.pop("AXOR_BENCH_SPEND_CAP", None); os.environ.pop("AXOR_BENCH_SPEND_LOG", None)
A.OpenRouterLLM._post = lambda self, body: or_resp(provider="Together")
llm5 = A.OpenRouterLLM(model="anthropic/claude-haiku-5.5", max_tokens=4096)
llm5.query("q", _FakeRuntime(), messages=USER)
R["t5_provider_visible"] = {"provider": llm5.last_provider, "is_anthropic": llm5.last_provider == "Anthropic",
                            "pass": llm5.last_provider == "Together"}

R["kernel_commit"] = P.kernel_commit()
R["kernel_is_f227951"] = (R["kernel_commit"] or "").startswith("f2279515")
R["ALL_PASS"] = all(v["pass"] for k, v in R.items() if isinstance(v, dict) and "pass" in v) and R["kernel_is_f227951"]
print(json.dumps(R, indent=1, default=str))
json.dump(R, open("/home/user/ajar-wt/experiments/ajar/results/test_or_patch.json", "w"), indent=1, default=str)
