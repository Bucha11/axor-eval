from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from axor_eval.deprivation.engine import ToolDeprivationEngine


class ReplayRecorder:
    """
    Records a full eval run to a JSONL file for third-party reproducibility (§8).

    Each line in the file is a typed record:
      {"type": "meta",   ...}   — scenario id, seed, env config, timestamp
      {"type": "action", ...}   — each tool call (name, args_repr)
      {"type": "fault",  ...}   — each FaultRecord from ToolDeprivationEngine.fault_log
      {"type": "result", ...}   — each tool result (stringified)

    On close() the file is finalised with a "close" sentinel.
    Caller is responsible for providing the ToolDeprivationEngine so the recorder
    can snapshot fault_log at close time.
    """

    def __init__(
        self,
        output_path: Path,
        scenario_id: str,
        engine: ToolDeprivationEngine,
        env_config: dict[str, Any] | None = None,
    ) -> None:
        self._path = output_path
        self._scenario_id = scenario_id
        self._engine = engine
        self._env_config = env_config or {}
        self._actions: list[dict[str, Any]] = []
        self._results: list[dict[str, Any]] = []
        self._closed = False

    def record_action(self, tool_name: str, args_repr: str = "") -> None:
        self._actions.append({"tool": tool_name, "args_repr": args_repr, "ts": time.time()})

    def record_result(self, tool_name: str, result_repr: str = "") -> None:
        self._results.append({"tool": tool_name, "result_repr": result_repr, "ts": time.time()})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        lines: list[dict[str, Any]] = [
            {
                "type": "meta",
                "scenario_id": self._scenario_id,
                "seed": self._engine._seed,
                "env_config": self._env_config,
                "ts": time.time(),
            }
        ]
        for action in self._actions:
            lines.append({"type": "action", **action})
        for fault in self._engine.fault_log:
            lines.append({"type": "fault", **dataclasses.asdict(fault)})
        for result in self._results:
            lines.append({"type": "result", **result})
        lines.append({"type": "close", "ts": time.time()})

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def __enter__(self) -> "ReplayRecorder":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
