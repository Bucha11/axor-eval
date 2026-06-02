from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, TYPE_CHECKING

from axor_core.contracts.invokable import Invokable
from axor_core.contracts.result import ExecutorEvent, ExecutorEventKind

from axor_eval.governed.bus import ToolResultBus

if TYPE_CHECKING:
    from axor_core.contracts.envelope import ExecutionEnvelope
    from axor_eval.contracts import AgentClaims


# ── Agent actions ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolOutcome:
    """A completed tool call as seen by the agent: the governed, possibly
    fault-injected result the agent must reason over."""
    tool: str
    args: dict[str, Any]
    result: Any


@dataclass(frozen=True)
class CallTool:
    """Agent decides to call a tool this step."""
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finish:
    """Agent decides to stop and emit its final answer + structured claims."""
    text: str
    claims: "AgentClaims | None" = None


# behaviour(history) → next action. Pure step function: the agent reacts to the
# full history of governed tool outcomes so far. Sync for ergonomics.
Behavior = Callable[[list[ToolOutcome]], "CallTool | Finish"]

_DEFAULT_USAGE = {"input_tokens": 100, "output_tokens": 50, "tool_tokens": 10}


class ReactiveAgent(Invokable):
    """
    Reactive agent driven through a real GovernedSession.

    On each step the behaviour sees every prior governed `ToolOutcome` and returns
    either a `CallTool` (emitted as a TOOL_USE event the IntentLoop intercepts and
    resolves) or a `Finish` (final text + claims). Tool results are awaited back
    from the ToolResultBus that axor-core pushes into, so the agent genuinely
    reacts to fault-injected / governance-observed outputs.

    `result` exposes the captured Finish after the stream completes, so the runner
    can read the agent's structured claims.
    """

    def __init__(
        self,
        behavior: Behavior,
        usage: dict[str, int] | None = None,
        max_steps: int = 50,
    ) -> None:
        self._behavior = behavior
        self._usage = dict(usage) if usage else dict(_DEFAULT_USAGE)
        self._max_steps = max_steps
        self._bus = ToolResultBus()
        self._final: Finish | None = None

    # axor-core duck-types this: presence of get_bus() makes the IntentLoop push
    # tool results into the bus instead of yielding them as TEXT events.
    def get_bus(self) -> ToolResultBus:
        return self._bus

    @property
    def result(self) -> "Finish | None":
        return self._final

    async def stream(self, envelope: "ExecutionEnvelope") -> AsyncIterator[ExecutorEvent]:
        history: list[ToolOutcome] = []
        for _ in range(self._max_steps):
            action = self._behavior(history)

            if isinstance(action, Finish):
                self._final = action
                yield ExecutorEvent(
                    kind=ExecutorEventKind.TEXT,
                    payload={"text": action.text},
                    node_id=envelope.node_id,
                )
                yield ExecutorEvent(
                    kind=ExecutorEventKind.STOP,
                    payload={"usage": dict(self._usage)},
                    node_id=envelope.node_id,
                )
                return

            tool_use_id = uuid.uuid4().hex
            yield ExecutorEvent(
                kind=ExecutorEventKind.TOOL_USE,
                payload={"tool": action.tool, "args": action.args, "tool_use_id": tool_use_id},
                node_id=envelope.node_id,
            )
            # IntentLoop resolves + executes (OBSERVE never blocks) and pushes the
            # real result into the bus; await it before the next decision.
            result = await self._bus.get(tool_use_id)
            history.append(ToolOutcome(tool=action.tool, args=dict(action.args), result=result))

        # Safety stop if the behaviour never finishes.
        self._final = Finish(text="[reactive agent reached max_steps]")
        yield ExecutorEvent(
            kind=ExecutorEventKind.STOP,
            payload={"usage": dict(self._usage)},
            node_id=envelope.node_id,
        )
