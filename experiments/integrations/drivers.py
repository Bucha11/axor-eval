"""One governed agent session per integration, driven call by call without a model.

Every driver offers the same surface:

    s = DRIVER(cfg, task, confirmer=..., structured=...)   # one agent session
    out = await s.call(tool, args, output)                  # the agent proposes a call;
                                                            # the tool, if it runs, returns
                                                            # `output` (None: the tool raises)
    s.governor                                              # the session's kernel governor
    await s.close()

``out`` is an ``Outcome``: whether the tool ran, the arguments it ran with, the
kernel's category for a refusal, the confirmations asked, and what the agent was
given back. ``shim`` is the AgentDojo shim's own sequence (axor-eval
experiments/ajar/axor_ajar.py + final_live/decisions_live.py) on a bare governor; the
other five go through each package's public path:

    wrap        axor_wrap.WrappedToolset (governance=, begin, call)
    langchain   axor_langchain.AxorMiddleware.wrap_tool_call (the agent's tool hook)
    claude      axor_claude GatedSession + the real ClaudeCodeExecutor; a scripted
                client stands where the Anthropic API would (no request leaves)
    openrouter  axor_openrouter GatedSession + the real OpenRouterExecutor; a scripted
                transport stands where OpenRouter would
    daemon      axor-daemon (in process): DaemonEnforcer.open_session(task) + execute
"""
from __future__ import annotations

import asyncio
import json
import re
import types
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Outcome:
    executed: bool
    category: str | None  # the kernel's refusal category; None when it ran
    ran_args: dict | None  # what the tool received
    view: Any  # what the agent was given back
    confirmations: int = 0
    note: str = ""


def _deny_events(g) -> list:
    return [e for e in g.trace_events if getattr(e, "kind", None) is not None
            and getattr(e.kind, "value", str(e.kind)).endswith("denied")]


class _Base:
    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        self.cfg, self.task, self.confirmer, self.structured = cfg, task, confirmer, structured

    async def close(self) -> None:
        return None


# ── the AgentDojo shim: axor_ajar's sequence on a bare ToolCallGovernor ─────────────
class Shim(_Base):
    name = "shim"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured)
        from axor_core.governor import ToolCallGovernor
        kw = cfg.as_governor_kwargs()
        if confirmer is not None:
            kw["confirmer"] = confirmer
        g = ToolCallGovernor(**kw)
        g.register_task(task)
        if cfg.grant_args:
            g.grants.from_request(task)
        self.governor = g

    async def call(self, tool, args, output):
        import axor_ajar
        g = self.governor
        c0 = g.confirmations
        dec = g.evaluate(tool, dict(args))
        if not dec.allowed:
            return Outcome(False, dec.category, None, None, g.confirmations - c0)
        run = axor_ajar.spend_args(dec, dict(args))
        if getattr(dec, "grant_id", None) is not None:
            key = g.spend(dec, run)
            if key is not None:
                g.grant_store.commit(key)
        # the live executor registers only clean executions (decisions_live.py)
        view = axor_ajar.present(g, dec, output, tool, run) if output is not None else None
        return Outcome(True, None, run, view, g.confirmations - c0)


# ── axor-wrap ─────────────────────────────────────────────────────────────────────────
class Wrap(_Base):
    name = "wrap"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured)
        from axor_wrap.runtime import WrappedToolset
        self._out: dict = {}
        self._ran: list = []
        self._ts = WrappedToolset({t: self._tool(t) for t in tools}, [], governance=cfg,
                                  confirmer=confirmer, structured=structured)
        self._ts.begin(task)
        self.governor = self._ts._governor

    def _tool(self, name):
        def fn(**kw):
            self._ran.append(dict(kw))
            out = self._out[name]
            if out is None:
                raise RuntimeError("tool error (recorded)")
            return out
        return fn

    async def call(self, tool, args, output):
        from axor_wrap.errors import ToolDenied
        self._out[tool] = output
        g, c0, n0 = self.governor, self.governor.confirmations, len(self._ran)
        try:
            view = self._ts.call(tool, dict(args))
        except ToolDenied as e:
            return Outcome(False, e.category, None, None, g.confirmations - c0)
        except RuntimeError:
            view = None
        return Outcome(len(self._ran) > n0, None, self._ran[-1], view, g.confirmations - c0)


# ── axor-langchain: AxorMiddleware.wrap_tool_call ─────────────────────────────────────
class LangChain(_Base):
    name = "langchain"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured)
        from axor_langchain import AxorMiddleware
        from langchain_core.messages import HumanMessage
        self.mw = AxorMiddleware(governance=cfg, confirmer=confirmer, structured=structured,
                                 telemetry="off")
        self.governor = self.mw._tool_gate.gate.governor
        self._state = {"messages": [HumanMessage(task)]}
        self._n = 0

    async def call(self, tool, args, output):
        from langchain.agents.middleware import ToolCallRequest
        from langchain_core.messages import ToolMessage
        self._n += 1
        req = ToolCallRequest(tool_call={"name": tool, "args": dict(args), "id": f"c{self._n}"},
                              tool=None, state=self._state, runtime=None)
        ran = []

        def handler(r):
            ran.append(dict(r.tool_call["args"]))
            if output is None:
                raise RuntimeError("tool error (recorded)")
            return ToolMessage(content=output, tool_call_id=r.tool_call["id"])
        g, c0 = self.governor, self.governor.confirmations
        try:
            msg = self.mw.wrap_tool_call(req, handler)
        except RuntimeError:
            return Outcome(True, None, ran[-1], None, g.confirmations - c0)
        if getattr(msg, "status", "success") == "error" and not ran:
            m = re.match(r"tool_denied: governance \(([^)]*)\)", msg.content)
            return Outcome(False, m.group(1) if m else msg.content, None, None, g.confirmations - c0)
        return Outcome(bool(ran), None, ran[-1] if ran else None, msg.content, g.confirmations - c0)


# ── session-based adapters: the model is a conductor fed one call at a time ─────────
class _Conductor:
    """Stands where the model would. Each model turn asks it for the next call; the
    previous call's outcome is read off what the session handed the model back."""

    def __init__(self):
        self.next_calls: asyncio.Queue = asyncio.Queue()
        self.outcomes: asyncio.Queue = asyncio.Queue()
        self.pending = None  # (tool, args, output, trace mark, confirmations mark)
        self.ran: list = []
        self.governor = None
        self.n = 0

    def handler(self, name):
        from axor_core.capability.executor import ToolHandler
        cond = self

        class H(ToolHandler):
            @property
            def name(self):
                return name

            async def execute(self, args):
                cond.ran.append(dict(args))
                out = cond.pending[2]
                if out is None:
                    raise RuntimeError("tool error (recorded)")
                return out
        return H()

    async def turn(self, returned):
        """Called at the start of each model turn with what the previous call returned
        to the model (None on the first turn). Returns the next call or None."""
        if self.pending is not None:
            tool, args, output, ran0, deny0, c0 = self.pending
            g = self.governor
            executed = len(self.ran) > ran0
            denials = _deny_events(g)[deny0:]
            cat = None
            if not executed:
                cat = (denials[-1].payload.get("category") if denials
                       else "session:" + json.dumps(returned, default=str)[:120])
            view = returned if executed and output is not None else None
            await self.outcomes.put(Outcome(executed, cat, self.ran[-1] if executed else None, view,
                                            g.confirmations - c0))
            self.pending = None
        nxt = await self.next_calls.get()
        if nxt is None:
            return None
        tool, args, output = nxt
        self.pending = (tool, args, output, len(self.ran), len(_deny_events(self.governor)),
                        self.governor.confirmations)
        self.n += 1
        return tool, args, f"call_{self.n}"


class _SessionDriver(_Base):
    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured)
        self.cond = _Conductor()
        self.tools = tuple(tools)

    def _policy(self):
        from axor_core.contracts.policy import ExecutionPolicy, ToolPolicy
        return ExecutionPolicy(tool_policy=ToolPolicy(extra_allowed=self.tools))

    def _start(self, session):
        self.session = session
        self.governor = session._cap_executor.gate.governor
        self.cond.governor = self.governor
        self._run = asyncio.ensure_future(session.run(self.task))

    async def call(self, tool, args, output):
        if self._run.done():
            raise RuntimeError(f"the session ended early: {self._run.exception() or self._run.result()}")
        await self.cond.next_calls.put((tool, dict(args), output))
        get = asyncio.ensure_future(self.cond.outcomes.get())
        done, _ = await asyncio.wait({get, self._run}, return_when=asyncio.FIRST_COMPLETED)
        if get not in done:
            get.cancel()
            raise RuntimeError(f"the session ended mid-call: {self._run.exception() or self._run.result()}")
        return get.result()

    async def close(self):
        await self.cond.next_calls.put(None)
        try:
            await asyncio.wait_for(self._run, timeout=30)
        except Exception:
            pass


class Claude(_SessionDriver):
    name = "claude"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured, tools)
        from axor_claude import ClaudeCodeExecutor, Gate, GatedCapabilityExecutor, GatedSession
        cap = GatedCapabilityExecutor(Gate.from_config(cfg, confirmer=confirmer, structured=structured))
        for t in self.tools:
            cap.register(self.cond.handler(t))
        ex = ClaudeCodeExecutor(api_key="sk-ant-no-request-leaves", enable_prompt_cache=False)
        ex._client = _ScriptedAnthropic(self.cond)
        self._start(GatedSession(executor=ex, capability_executor=cap, default_policy=self._policy()))


class _ScriptedAnthropic:
    """The Anthropic client surface ClaudeCodeExecutor uses: messages.stream(...)."""

    def __init__(self, cond):
        self.messages = types.SimpleNamespace(stream=lambda **kw: _ScriptedStream(cond, kw))


class _ScriptedStream:
    def __init__(self, cond, kw):
        self.cond, self.kw = cond, kw

    async def __aenter__(self):
        returned = None
        last = self.kw["messages"][-1] if self.kw["messages"] else None
        if last and last["role"] == "user" and isinstance(last["content"], list):
            blk = next((b for b in last["content"] if b.get("type") == "tool_result"), None)
            if blk is not None:
                returned = blk.get("content")
        nxt = await self.cond.turn(returned)
        ns = types.SimpleNamespace
        if nxt is None:
            self.events = [ns(type="message_start", message=ns(usage=ns(input_tokens=0))),
                           ns(type="content_block_start", index=0, content_block=ns(type="text")),
                           ns(type="content_block_delta", index=0, delta=ns(text="done")),
                           ns(type="content_block_stop", index=0),
                           ns(type="message_delta", usage=ns(output_tokens=0), delta=ns(stop_reason="end_turn")),
                           ns(type="message_stop")]
        else:
            tool, args, tid = nxt
            self.events = [ns(type="message_start", message=ns(usage=ns(input_tokens=0))),
                           ns(type="content_block_start", index=0,
                              content_block=ns(type="tool_use", id=tid, name=tool)),
                           ns(type="content_block_delta", index=0,
                              delta=ns(partial_json=json.dumps(args))),
                           ns(type="content_block_stop", index=0),
                           ns(type="message_delta", usage=ns(output_tokens=0), delta=ns(stop_reason="tool_use")),
                           ns(type="message_stop")]
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e
        return gen()


class OpenRouter(_SessionDriver):
    name = "openrouter"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured, tools)
        from axor_openrouter import make_session
        handlers = [self.cond.handler(t) for t in self.tools]
        self._start(make_session(api_key="sk-or-no-request-leaves", handlers=handlers, governance=cfg,
                                 confirmer=confirmer, structured=structured, policy=self._policy(),
                                 transport=_ScriptedTransport(self.cond)))


class _ScriptedTransport:
    """The OpenRouterTransport surface OpenRouterExecutor uses: stream(api_key, body)."""

    def __init__(self, cond):
        self.cond = cond

    async def stream(self, api_key, body):
        msgs = body.get("messages") or []
        returned = msgs[-1].get("content") if msgs and msgs[-1].get("role") == "tool" else None
        nxt = await self.cond.turn(returned)
        if nxt is None:
            yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}
            return
        tool, args, tid = nxt
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": tid, "function": {
            "name": tool, "arguments": json.dumps(args)}}]}, "finish_reason": "tool_calls"}]}


# ── axor-daemon, in process: the enforcer the socket server calls ──────────────────
class Daemon(_Base):
    name = "daemon"

    def __init__(self, cfg, task, confirmer=None, structured=None, tools=()):
        super().__init__(cfg, task, confirmer, structured)
        from axor_core.contracts.policy import ExecutionPolicy
        from axor_daemon.enforcer import DaemonEnforcer
        self.cond = _Conductor()
        self.cond.pending = (None, None, None, 0, 0, 0)
        handlers = {t: self.cond.handler(t) for t in tools}
        gov = _FixedGovernance(cfg, confirmer)
        self.enf = DaemonEnforcer(ExecutionPolicy(), handlers, governance=gov,
                                  operator_allowed=frozenset(tools), confirm=None,
                                  structured=structured)
        self.sess = self.enf.open_session(task)
        self.governor = self.sess.governor
        self.tools = frozenset(tools)
        self._n = 0

    async def call(self, tool, args, output):
        self._n += 1
        g, c0, n0 = self.governor, self.governor.confirmations, len(self.cond.ran)
        self.cond.pending = (tool, args, output, n0, 0, c0)
        try:
            decision, result, reason = await self.enf.execute(f"c{self._n}", tool, dict(args),
                                                              self.tools, self.sess)
        except RuntimeError:
            return Outcome(True, None, self.cond.ran[-1], None, g.confirmations - c0)
        if decision == "denied":
            m = re.match(r"governance \(([^)]*)\)", reason or "")
            return Outcome(False, m.group(1) if m else reason, None, None, g.confirmations - c0)
        return Outcome(True, None, self.cond.ran[-1], result, g.confirmations - c0)


class _FixedGovernance:
    """The daemon's --governance config, with the episode's confirmer in place of the
    operator socket (the daemon passes confirmer through as_governor_kwargs)."""

    def __init__(self, cfg, confirmer):
        self.cfg, self.confirmer = cfg, confirmer
        self.grant_args = cfg.grant_args

    def as_governor_kwargs(self):
        kw = self.cfg.as_governor_kwargs()
        if self.confirmer is not None:
            kw["confirmer"] = self.confirmer
        return kw


DRIVERS = {d.name: d for d in (Shim, Wrap, LangChain, Claude, OpenRouter, Daemon)}
