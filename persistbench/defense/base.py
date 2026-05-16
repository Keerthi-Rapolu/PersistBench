"""PersistBench Defense Plugin API — V4.

Design ref: DESIGN_DOC.md Appendix B (Defense Middleware Layer)

Every baseline defense and all community submissions implement DefensePlugin.
The ReplayEngine calls hooks in the correct lifecycle order; plugin authors
override only the hooks they need.

Hook call order per turn:
  1. on_session_start  (once per session)
  2. pre_turn          (before backend.send)
  3. pre_memory_write  (if fragment is being planted)
  4. post_turn         (after backend.send)
  5. on_session_end    (once per session, after all turns)
"""
from __future__ import annotations

import time
import uuid
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DefenseAction(str, Enum):
    ALLOW      = "allow"
    BLOCK      = "block"
    QUARANTINE = "quarantine"
    SANITIZE   = "sanitize"
    FLAG       = "flag"


@dataclass
class MemoryUpdate:
    """Represents a pending memory write that defenses can intercept."""
    fragment_id:  str
    content:      str
    session_id:   int
    turn_id:      int
    content_hash: str
    metadata:     dict[str, Any] = field(default_factory=dict)


@dataclass
class DefenseFlag:
    """Emitted when a defense believes it has detected an attack."""
    flag_id:      str
    session_id:   int
    turn_id:      Optional[int]
    threat_class: str           # "SBMP" | "TSCC" | "CACP" | "unknown"
    confidence:   float         # [0, 1]
    action:       DefenseAction
    rationale:    str
    fragment_id:  Optional[str] = None
    is_true_positive: Optional[bool] = None  # filled by oracle after run
    timestamp:    float = field(default_factory=time.time)

    @staticmethod
    def new(session_id: int, turn_id: Optional[int], threat_class: str,
            confidence: float, action: DefenseAction, rationale: str,
            fragment_id: Optional[str] = None) -> "DefenseFlag":
        return DefenseFlag(
            flag_id=str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            threat_class=threat_class,
            confidence=confidence,
            action=action,
            rationale=rationale,
            fragment_id=fragment_id,
        )


class DefensePlugin(ABC):
    """Base class for all PersistBench defense plugins.

    Override any subset of hooks. Defaults are pass-through (no defense action).
    Flags are accumulated internally and retrieved by the engine after each session
    via get_and_clear_flags().
    """

    def __init__(self) -> None:
        self._flags: list[DefenseFlag] = []
        self._session_memory: dict = {}  # plugin-local per-session state

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def defense_class(self) -> str:
        """One of: prompt_level | memory_level | tool_integrity | pipeline_isolation | composite"""
        return "unknown"

    # ── flag management ───────────────────────────────────────────────────────

    def emit(self, flag: DefenseFlag) -> None:
        self._flags.append(flag)

    def get_and_clear_flags(self) -> list[DefenseFlag]:
        flags = self._flags[:]
        self._flags.clear()
        return flags

    # ── lifecycle hooks ───────────────────────────────────────────────────────

    def on_scenario_start(self, scenario: dict) -> None:
        """Called once before the first session. Reset all state here."""
        self._flags.clear()
        self._session_memory.clear()

    def on_session_start(self, session_id: int, memory_snapshot: dict) -> None:
        """Called at the start of each session.

        memory_snapshot: current {entry_id: entry_dict} from the engine.
        """

    def on_session_end(self, session_id: int, memory_snapshot: dict) -> None:
        """Called at the end of each session, after all turns complete."""

    def pre_turn(self, content: str, session_id: int, turn_id: int,
                 fragment_id: Optional[str], is_benign: bool) -> str:
        """Called before a turn is sent to the agent backend.

        Returns the (potentially sanitized) content. Return empty string to
        suppress the turn and emit a BLOCK flag externally.
        """
        return content

    def pre_memory_write(self, update: MemoryUpdate) -> Optional[MemoryUpdate]:
        """Called before a fragment is committed to memory.

        Return the update to allow it (possibly modified), or None to block it.
        Emit a DefenseFlag inside this method when blocking/flagging.
        """
        return update

    def post_turn(self, response: str, session_id: int, turn_id: int) -> str:
        """Called after the agent produces a response. Can sanitize outputs."""
        return response

    def reset(self) -> None:
        """Full reset between benchmark runs (called by engine before each scenario)."""
        self._flags.clear()
        self._session_memory.clear()
