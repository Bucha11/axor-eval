from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axor_eval.deprivation.engine import FaultRecord, ToolDeprivationEngine


@dataclass(frozen=True)
class ReplayManifest:
    """Parsed header from a replay file."""
    scenario_id: str
    seed: str
    env_config: dict[str, Any]


class ReplayPlayer:
    """
    Replays a recorded eval run (§8).

    Reads the JSONL produced by ReplayRecorder, reconstructs the
    ToolDeprivationEngine with the same seed and registered modes,
    then drives an agent stub (or any callable) through the same action
    sequence — producing an identical fault sequence without re-generating
    the scenario.
    """

    def __init__(self, replay_path: Path) -> None:
        self._path = replay_path
        self._lines = self._load(replay_path)

    @staticmethod
    def _load(path: Path) -> list[dict[str, Any]]:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    lines.append(json.loads(raw))
        return lines

    @property
    def manifest(self) -> ReplayManifest:
        for line in self._lines:
            if line.get("type") == "meta":
                return ReplayManifest(
                    scenario_id=line["scenario_id"],
                    seed=line["seed"],
                    env_config=line.get("env_config", {}),
                )
        raise ValueError("replay file missing meta record")

    def fault_records(self) -> list[FaultRecord]:
        return [
            FaultRecord(
                tool_name=line["tool_name"],
                mode=line["mode"],
                seed=line["seed"],
                canary=line["canary"],
            )
            for line in self._lines
            if line.get("type") == "fault"
        ]

    def actions(self) -> list[dict[str, Any]]:
        return [line for line in self._lines if line.get("type") == "action"]

    def reconstruct_engine(self) -> ToolDeprivationEngine:
        """
        Reconstruct a ToolDeprivationEngine with the same seed and modes.
        Modes are derived from the fault records — one register() call per
        unique (tool_name, mode) pair.
        """
        manifest = self.manifest
        engine = ToolDeprivationEngine(seed=manifest.seed)
        seen: set[tuple[str, str]] = set()
        for record in self.fault_records():
            key = (record.tool_name, record.mode)
            if key not in seen:
                engine.register(record.tool_name, record.mode)
                seen.add(key)
        return engine
