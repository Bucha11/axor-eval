"""Bootstrap for the composition repros, following the `_corepath.py` convention
of the other experiment directories: put the sibling axor-core checkout on
``sys.path`` (override with ``AXOR_CORE_REPO``).

It also carries the small builders the repros share — an envelope whose
capabilities are resolved exactly as ``EnvelopeBuilder`` resolves them, a
recording tool handler and a scripted agent — so each repro is a single
``python`` run with no pytest fixtures behind it. Audits that assert "the tool
did not run" need the handler, not a verdict.
"""
from __future__ import annotations

import os
import sys
from typing import AsyncIterator

sys.path.insert(
    0, os.environ.get("AXOR_CORE_REPO")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "axor-core")
)

from axor_core.capability.executor import ToolHandler            # noqa: E402
from axor_core.capability.resolver import CapabilityResolver      # noqa: E402
from axor_core.contracts.cancel import make_token                 # noqa: E402
from axor_core.contracts.context import (                         # noqa: E402
    ContextFragment, ContextView, LineageSummary,
)
from axor_core.contracts.envelope import ExecutionEnvelope, ExportContract  # noqa: E402
from axor_core.contracts.invokable import Invokable               # noqa: E402
from axor_core.contracts.result import ExecutorEvent, ExecutorEventKind     # noqa: E402


def say(tag: str, holds: bool, detail: str) -> None:
    """One line per check. CONFIRMED = the claim under test holds as stated."""
    print(f"[{'CONFIRMED' if holds else 'REFUTED  '}] {tag}: {detail}")


def envelope(policy, node_id: str = "n0") -> ExecutionEnvelope:
    """An envelope whose capabilities are resolved from `policy`, exactly as
    EnvelopeBuilder does — so the capability gate sees what it would at runtime."""
    lineage = LineageSummary(
        node_id=node_id, parent_id=None, depth=0,
        ancestry_ids=(), inherited_restrictions=(),
    )
    context = ContextView(
        node_id=node_id, working_summary="t",
        visible_fragments=[ContextFragment(kind="fact", content="c",
                                           token_estimate=1, source="t")],
        active_constraints=[], lineage=lineage, token_count=1, compression_ratio=1.0,
    )
    return ExecutionEnvelope(
        node_id=node_id, task="t", context=context, policy=policy, lineage=lineage,
        capabilities=CapabilityResolver().resolve(policy),
        export_contract=ExportContract(
            mode=policy.export_mode, allowed_fields=frozenset(["output"]),
            max_export_tokens=1024,
        ),
        cancel_token=make_token(),
    )


def tool_event(tool: str, args: dict, node_id: str = "n0") -> ExecutorEvent:
    return ExecutorEvent(kind=ExecutorEventKind.TOOL_USE,
                         payload={"tool": tool, "args": args}, node_id=node_id)


class RecordingHandler(ToolHandler):
    """Records every invocation, so "denied" can be told from "ran anyway"."""

    def __init__(self, name: str, output: str = "ok", log: list | None = None) -> None:
        self._name, self._output = name, output
        self.log = log if log is not None else []

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, args) -> str:
        self.log.append((self._name, dict(args)))
        return self._output


class ScriptedAgent(Invokable):
    """An agent that emits a fixed list of (tool, args) calls, then stops."""

    def __init__(self, calls: list[tuple[str, dict]], on_envelope=None) -> None:
        self._calls, self._on_envelope = calls, on_envelope

    async def stream(self, envelope) -> AsyncIterator[ExecutorEvent]:
        if self._on_envelope is not None:
            self._on_envelope(envelope)
        for tool, args in self._calls:
            yield tool_event(tool, args, envelope.node_id)
        yield ExecutorEvent(kind=ExecutorEventKind.STOP, payload={"usage": {}},
                            node_id=envelope.node_id)
