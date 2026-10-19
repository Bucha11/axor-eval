"""Drop-in hardening of the AgentDojo live harness for a Claude run — applied by import
(monkeypatch), so the frozen axor-core/examples harness file is not edited. Equivalent
in-place diff is in results/claude_harness.patch.

Adds to RawAnthropicLLM:
  * retries with exponential backoff on 429/5xx/timeout (up to AXOR_BENCH_RETRIES=5);
  * on terminal failure -> ApiError; the episode is marked api_error=True, NOT counted as
    utility 0, and its task id is appended to the rerun list (AXOR_BENCH_RERUN_LIST);
  * usage logging via a spend ledger line (so AXOR_BENCH_SPEND_CAP works for Anthropic) and
    a _spend_guard() check before every call;
  * explicit thinking (adaptive) recorded into trace metadata; max_tokens from AXOR_BENCH_MAXTOK.
"""
import os, sys, json, time, socket, urllib.request, urllib.error

sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
import agentdojo_adapter as A  # noqa: E402
import run_agentdojo as R  # noqa: E402
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, EmptyEnv  # noqa: E402

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00),
          "claude-haiku-4-5-20251001": (1.00, 5.00)}
_RETRYABLE_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    """Raised after retries are exhausted; the episode is a rerun candidate, not utility 0."""


# ── swappable transport (test replaces this; real one hits the network) ─────────
def _http_real(self, body):
    req = urllib.request.Request(
        _API_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-api-key": self._key,
                 "anthropic-version": _API_VERSION}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:   # raises raw HTTPError/URLError
        return json.load(resp)


def _is_retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_CODES
    return isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError))


def _post_retry(self, body):
    attempts = int(os.environ.get("AXOR_BENCH_RETRIES", "5"))
    base = float(os.environ.get("AXOR_BENCH_BACKOFF", "2"))
    self._retries = 0
    last = None
    for i in range(attempts):
        try:
            return self._http(body)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not _is_retryable(exc) or i == attempts - 1:
                break
            self._retries += 1
            time.sleep(base * (2 ** i))   # 2,4,8,16s …
    raise ApiError(f"anthropic failed after {self._retries + 1} attempt(s): "
                   f"{type(last).__name__}: {last}")


def _anthropic_cost(model, usage):
    pin, pout = _PRICE.get(model, (0.0, 0.0))
    return (usage.get("input_tokens", 0) / 1e6) * pin + (usage.get("output_tokens", 0) / 1e6) * pout


def _record(model, usage):
    path = os.environ.get("AXOR_BENCH_SPEND_LOG")
    if not path:
        return
    rec = {"model": model, "cost": _anthropic_cost(model, usage),
           "prompt_tokens": usage.get("input_tokens"),
           "completion_tokens": usage.get("output_tokens"),
           "reasoning_tokens": (usage.get("output_tokens") if usage.get("thinking") else None)}
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
    A._spend_guard()                                   # cap now enforced for Anthropic too
    system, anthropic_messages = A._messages_to_anthropic(messages)
    tools = [{"name": f.name, "description": f.description,
              "input_schema": f.parameters.model_json_schema()} for f in runtime.functions.values()]
    body = {"model": self.model, "max_tokens": self.max_tokens,
            "messages": anthropic_messages, "tools": tools, "temperature": 0.0}
    if system:
        body["system"] = system
    # Thinking: explicit, ON. NOTE: claude-haiku-5-5 / claude-sonnet-5-5 REJECT budget_tokens
    # (HTTP 400) — a fixed thinking budget is not expressible on 5.5; adaptive + effort is the
    # only valid form, so we send adaptive and record the config in trace metadata.
    self.think_cfg = None
    if os.environ.get("AXOR_BENCH_THINKING", "1") != "0":
        self.think_cfg = {"type": "adaptive"}
        body["thinking"] = self.think_cfg
        eff = os.environ.get("AXOR_BENCH_EFFORT")
        if eff:
            body["output_config"] = {"effort": eff}
    resp = self._post(body)                            # retries inside; ApiError if terminal
    usage = resp.get("usage") or {}
    usage["thinking"] = bool(self.think_cfg)
    _record(self.model, usage)
    self.last_usage = usage
    content = resp.get("content", []) or []
    self.last_thinking_blocks = sum(1 for b in content if b.get("type") in ("thinking", "redacted_thinking"))
    text_blocks = [text_content_block_from_string(b["text"]) for b in content if b.get("type") == "text"]
    tool_calls = [FunctionCall(id=b["id"], function=b["name"], args=b.get("input", {}) or {})
                  for b in content if b.get("type") == "tool_use"]
    assistant = ChatAssistantMessage(role="assistant", content=text_blocks,
                                     tool_calls=tool_calls if resp.get("stop_reason") == "tool_use" else None)
    return query, runtime, env, [*messages, assistant], extra_args


def apply():
    A.RawAnthropicLLM._http = _http_real
    A.RawAnthropicLLM._post = _post_retry
    A.RawAnthropicLLM.query = _query
    A.ApiError = ApiError
    _patch_save_and_runbenign()


def _patch_save_and_runbenign():
    _orig_save = R._save_trajectory

    def save(rec, ut_id, governed, utility, tools_executor, cost=None, api_error=False):
        _orig_save(rec, ut_id, governed, utility, tools_executor, cost=cost)
        p = R._traj_path(ut_id, governed)
        if not p or not os.path.exists(p):
            return
        d = json.load(open(p))
        llm = getattr(rec, "inner", rec)
        d["thinking"] = getattr(llm, "think_cfg", None)
        d["max_tokens"] = getattr(llm, "max_tokens", None)
        d["thinking_blocks_seen"] = getattr(llm, "last_thinking_blocks", None)
        d["api_error"] = api_error
        d["retries"] = getattr(llm, "_retries", 0)
        json.dump(d, open(p, "w"), indent=1, default=str)
    R._save_trajectory = save

    def run_benign(governed, suite):
        from agentdojo_adapter import _spend_total
        utils, rerun = [], []
        label = "GOVERNED " if governed else "UNDEFENDED"
        pipeline, ex = R.build_pipeline(governed)      # once per condition; executor accumulates
        for ut_id in R.USER_TASKS:
            p = R._traj_path(ut_id, governed)
            if p and os.path.exists(p):
                try:
                    utils.append(bool(json.load(open(p)).get("utility"))); continue
                except Exception:
                    pass
            ut = suite.get_user_task_by_id(ut_id)
            if hasattr(ex, "current_user_task"):
                ex.current_user_task = ut
            before = _spend_total()
            try:
                utility, _ = suite.run_task_with_pipeline(pipeline, ut, None, {})
            except A.SpendCapReached as e:
                print(f"  [{label}] {ut_id}: SPEND CAP — {e}"); break
            except ApiError as e:                      # terminal API failure
                print(f"  [{label}] {ut_id}: API_ERROR (rerun, NOT utility 0) — {e}")
                rerun.append(ut_id)
                R._save_trajectory(pipeline._recorder, ut_id, governed, None, ex,
                                   cost=round(_spend_total() - before, 6), api_error=True)
                continue
            utils.append(utility)
            R._save_trajectory(pipeline._recorder, ut_id, governed, utility, ex,
                               cost=round(_spend_total() - before, 6))
        rl = os.environ.get("AXOR_BENCH_RERUN_LIST")
        if rl and rerun:
            with open(rl, "a") as f:
                for t in rerun:
                    f.write(t + "\n")
        return utils, ex
    R.run_benign = run_benign
