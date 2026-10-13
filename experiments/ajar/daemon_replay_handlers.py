"""Tool handlers for an axor-daemon serving AgentDojo replays (Ajar, replay_runs).

Loaded by the daemon's own CLI (``--handler daemon_replay_handlers:T_<tool>``), one
class per tool, named from $AJAR_REPLAY_TOOLS. A handler does not run AgentDojo: the
harness has already produced the step's output (Ajar's prefix runner, or the replay's
environment) and writes it to $AJAR_REPLAY_FILE just before sending the call; the
handler returns that text, so it is what the daemon registers in its ledger — the
same string the in-process wrapper registers.
"""
from __future__ import annotations

import os

from axor_core.capability.executor import ToolHandler

_FILE = os.environ.get("AJAR_REPLAY_FILE", "")


class _Replay(ToolHandler):
    tool = ""

    @property
    def name(self) -> str:
        return self.tool

    async def execute(self, args: dict) -> str:
        with open(_FILE) as f:
            return f.read()


for _t in filter(None, os.environ.get("AJAR_REPLAY_TOOLS", "").split(",")):
    globals()[f"T_{_t}"] = type(f"T_{_t}", (_Replay,), {"tool": _t})
