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

    async def get(self, tool_use_id: str, timeout: float = 10.0) -> Any:  # noqa: ASYNC109
        """Wait up to `timeout` seconds in TOTAL for this id's result.

        The timeout used to be applied per queue read inside the loop, so every
        push for some other id reset the clock: a stream of out-of-order results
        could keep one `get` waiting indefinitely while still calling itself a
        10-second wait. `asyncio.timeout` bounds the whole wait, which is what
        the parameter always claimed to do.

        ASYNC109 would have the caller wrap this call in `asyncio.timeout`
        rather than pass one. Here the parameter exists for its DEFAULT: a
        caller that thinks about none of this still gets a bounded wait instead
        of a coroutine parked forever on a result nobody will push.
        """
        if tool_use_id in self._buffered:
            return self._buffered.pop(tool_use_id)
        async with asyncio.timeout(timeout):
            while True:
                tid, result = await self._queue.get()
                if tid == tool_use_id:
                    return result
                self._buffered[tid] = result  # out-of-order push — keep for its own get()
