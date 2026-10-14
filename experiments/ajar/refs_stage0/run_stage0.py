"""Stage 0 run: o4-mini, undefended (no gate), tool outputs carry references (refs.py).

    AXOR_BENCH_SPEND_LOG=... AXOR_BENCH_SPEND_CAP=1 python run_stage0.py <opaque|hint> <outdir>

Pipeline as run_agentdojo.build_pipeline(governed=False), with RefToolsExecutor in place of
ToolsExecutor, and one element after the loop that resolves references in the final messages
for SCORING only (AgentDojo grades the model's answer and its calls; the user sees values, not
references). The model never sees that element's output. Each trajectory is saved with the
model's own messages (references as it wrote them) and the session's reference table.
"""
from __future__ import annotations

import copy
import zlib
import json
import os
import sys
from ast import literal_eval

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, load_system_message  # noqa: E402
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement  # noqa: E402
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, is_string_list  # noqa: E402
from agentdojo.functions_runtime import EmptyEnv, FunctionCall  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.types import ChatToolResultMessage, text_content_block_from_string  # noqa: E402

from agentdojo_adapter import OpenRouterLLM  # noqa: E402
from refs import RefTable  # noqa: E402


class RefToolsExecutor(BasePipelineElement):
    def __init__(self) -> None:
        self.table: RefTable | None = None
        self.calls: list[dict] = []  # per call: as written, as resolved, error

    def query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return query, runtime, env, messages, extra_args
        results = []
        for tc in messages[-1]["tool_calls"]:
            if tc.function not in (t.name for t in runtime.functions.values()):
                results.append(ChatToolResultMessage(role="tool", content=[text_content_block_from_string("")],
                                                     tool_call_id=tc.id, tool_call=tc,
                                                     error=f"Invalid tool {tc.function} provided."))
                continue
            args = dict(tc.args)
            for k, v in args.items():
                if isinstance(v, str) and is_string_list(v):
                    args[k] = literal_eval(v)
            resolved = self.table.resolve(args)
            res, err = runtime.run_function(env, tc.function, resolved)
            self.calls.append({"tool": tc.function, "written": args, "resolved": resolved, "error": err})
            results.append(ChatToolResultMessage(role="tool",
                                                 content=[text_content_block_from_string(self.table.format_output(res))],
                                                 tool_call_id=tc.id, tool_call=tc, error=err))
        return query, runtime, env, [*messages, *results], extra_args


class Recorder(BasePipelineElement):
    def __init__(self, inner):
        self.inner, self.name, self.last = inner, getattr(inner, "name", None), []

    def query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
        out = self.inner.query(query, runtime, env, messages, extra_args)
        self.last = list(out[3])
        return out


class ResolveForScoring(BasePipelineElement):
    """After the loop: a copy of the conversation with references resolved, for AgentDojo's
    grader (model output text and the calls' arguments). The model does not see it."""

    def __init__(self, ex: RefToolsExecutor) -> None:
        self.ex = ex

    def query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
        t = self.ex.table
        out = []
        for m in messages:
            m = copy.copy(m)
            if m["role"] == "assistant":
                if m.get("content"):
                    m["content"] = [{**b, "content": t.resolve(b.get("content"))} if isinstance(b, dict) else b
                                    for b in m["content"]]
                if m.get("tool_calls"):
                    m["tool_calls"] = [FunctionCall(function=c.function, args=t.resolve(dict(c.args)), id=c.id)
                                       for c in m["tool_calls"]]
            out.append(m)
        return query, runtime, env, out, extra_args


# (0c) own entities = the entity model's own set (config_m1_c814 audience: own addresses, accounts,
# and own file / event / e-mail / standing-order ids)
import yaml as _yaml  # noqa: E402
OWN = {s: set(map(str, _yaml.safe_load(open(os.path.join(HERE, "..", "config_m1_c814", f"{s}.yaml")))
                  .get("audience") or ())) for s in ("banking", "slack", "travel", "workspace")}


def main(fmt: str, outdir: str) -> None:
    sel = json.load(open(os.path.join(HERE, "tasks.json")))
    llm = Recorder(OpenRouterLLM(model="openai/o4-mini", max_tokens=4096))
    ex = RefToolsExecutor()
    pipeline = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), llm,
                              ToolsExecutionLoop([ex, llm]), ResolveForScoring(ex)])
    pipeline.name = "refs-stage0-meta-llama/Llama-3-70b-chat-hf"
    os.makedirs(outdir, exist_ok=True)
    seed = 0
    for s, items in sel.items():
        suite = get_suite("v1", s)
        for it in items:
            tid = it["task"]
            seed += 1
            ut = suite.get_user_task_by_id(tid)
            ex.table, ex.calls = RefTable(fmt, seed=zlib.crc32(f"{fmt}|{s}|{tid}".encode()),
                                          prompt=ut.PROMPT, own=OWN.get(s, ())), []
            try:
                util, _ = suite.run_task_with_pipeline(pipeline, ut, None, {})
                err = None
            except Exception as e:  # counted as a failure, never hidden
                util, err = False, f"{type(e).__name__}: {e}"
            print(f"  [{fmt}] {s} {tid:<14} utility={'Y' if util else 'n'}{'  ERROR ' + err if err else ''}", flush=True)
            json.dump({"suite": s, "user_task_id": tid, "tier": it["tier"], "format": fmt, "utility": bool(util),
                       "error": err, "prompt": ut.PROMPT, "messages": llm.last, "calls": ex.calls,
                       "refs": {str(tok): [k, v] for tok, (k, v) in ex.table.by_ref.items()},
                       "int_handles": [t for t in ex.table.by_ref if isinstance(t, int)]},
                      open(os.path.join(outdir, f"{s}_{tid}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
