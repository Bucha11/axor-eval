from __future__ import annotations

import asyncio
from typing import Any


class ToolResultBus:
    """
    Channel by which axor-core's IntentLoop returns tool results to a streaming
    executor (duck-typed: the executor exposes ``get_bus()`` and the loop calls
    ``push(tool_use_id, result)``).

    The reactive agent awaits ``get(tool_use_id)`` after emitting a TOOL_USE
    event; results that arrive for other ids are buffered so lookups never lose
    a push.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._buffered: dict[str, Any] = {}

    def push(self, tool_use_id: str, result: Any) -> None:
        self._queue.put_nowait((tool_use_id, result))

    async def get(self, tool_use_id: str, timeout: float = 10.0) -> Any:
        if tool_use_id in self._buffered:
            return self._buffered.pop(tool_use_id)
        while True:
            tid, result = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            if tid == tool_use_id:
                return result
            self._buffered[tid] = result  # out-of-order push — keep for its own get()
