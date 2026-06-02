from __future__ import annotations

from typing import Any, Callable

from axor_core.capability.executor import ToolHandler


class ToolHandlerAdapter(ToolHandler):
    """
    Adapts a (deprivation-wrapped) plain callable into a core ToolHandler so it
    can be registered in a CapabilityExecutor and driven by a GovernedSession.

    The wrapped callable is the deprivation-engine output, so fault injection
    (silent_fail / corrupt_retrieval / instruction_injection / tool_substitution)
    happens inside execute() exactly as in the lightweight runner.
    """

    def __init__(self, name: str, fn: Callable[..., Any]) -> None:
        self._name = name
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, args: dict[str, Any]) -> Any:
        # CapabilityExecutor passes the tool args dict; deprivation wrappers and
        # typical tools accept keyword args.
        if isinstance(args, dict):
            return self._fn(**args)
        return self._fn(args)
