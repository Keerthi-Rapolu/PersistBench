"""Defense 0 — No Defense (ND).

Pass-through baseline. All hooks are no-ops. Establishes the worst-case
upper bound for APS and lower bound for RLS that all active defenses are
measured against.

Design ref: DESIGN_DOC.md §15.3 Defense 0
"""
from __future__ import annotations

from persistbench.defense.base import DefensePlugin, MemoryUpdate


class NoDefense(DefensePlugin):
    """No defense — all fragments pass through unmodified."""

    @property
    def defense_class(self) -> str:
        return "none"

    def pre_memory_write(self, update: MemoryUpdate):
        return update  # allow everything
