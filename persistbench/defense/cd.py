"""Defense 6 — Composite Defense (CD).

Combines MW + TOH + PS applied together in sequence. This represents a
realistic "defense-in-depth" approach that achieves the highest overall
composite score at the cost of slightly lower UPS.

A fragment is blocked if ANY component defense blocks it.
A fragment is flagged if ANY component defense flags it.
Confidence is the maximum across components.

Design ref: DESIGN_DOC.md §15.3 Defense 6
Expected composite score: 0.617 (Table 4)
"""
from __future__ import annotations

from typing import Optional

from persistbench.defense.base import (
    DefenseAction, DefenseFlag, DefensePlugin, MemoryUpdate,
)
from persistbench.defense.mw  import MemoryWatermarking
from persistbench.defense.pls import PromptLevelSanitization
from persistbench.defense.ps  import ProvenanceScoring
from persistbench.defense.toh import ToolOutputHashing


class CompositeDefense(DefensePlugin):
    """MW + PLS + TOH + PS applied in sequence.

    Args:
        mw_eviction_window: passed to MemoryWatermarking (default 3)
        pls_block_threshold: passed to PromptLevelSanitization (default 0.45)
        toh_drift_threshold: passed to ToolOutputHashing (default 0.32)
        ps_risk_threshold: passed to ProvenanceScoring (default 0.50)
    """

    def __init__(
        self,
        mw_eviction_window:  int   = 3,
        pls_block_threshold: float = 0.45,
        toh_drift_threshold: float = 0.32,
        ps_risk_threshold:   float = 0.50,
    ) -> None:
        super().__init__()
        self._components: list[DefensePlugin] = [
            MemoryWatermarking(eviction_window=mw_eviction_window, block_on_create=True),
            PromptLevelSanitization(block_threshold=pls_block_threshold),
            ToolOutputHashing(drift_threshold=toh_drift_threshold),
            ProvenanceScoring(risk_threshold=ps_risk_threshold),
        ]

    @property
    def defense_class(self) -> str:
        return "composite"

    def on_scenario_start(self, scenario: dict) -> None:
        super().on_scenario_start(scenario)
        for c in self._components:
            c.on_scenario_start(scenario)

    def on_session_start(self, session_id: int, memory_snapshot: dict) -> None:
        for c in self._components:
            c.on_session_start(session_id, memory_snapshot)
        # Collect MW eviction flags
        for c in self._components:
            for flag in c.get_and_clear_flags():
                self._flags.append(flag)

    def on_session_end(self, session_id: int, memory_snapshot: dict) -> None:
        for c in self._components:
            c.on_session_end(session_id, memory_snapshot)
        for c in self._components:
            for flag in c.get_and_clear_flags():
                self._flags.append(flag)

    def pre_memory_write(self, update: MemoryUpdate) -> Optional[MemoryUpdate]:
        current = update
        for component in self._components:
            if current is None:
                break
            result = component.pre_memory_write(current)
            # Collect any flags emitted
            for flag in component.get_and_clear_flags():
                self._flags.append(flag)
            current = result
        return current

    def pre_turn(self, content: str, session_id: int, turn_id: int,
                 fragment_id, is_benign: bool) -> str:
        for c in self._components:
            content = c.pre_turn(content, session_id, turn_id, fragment_id, is_benign)
        return content

    def reset(self) -> None:
        super().reset()
        for c in self._components:
            c.reset()
