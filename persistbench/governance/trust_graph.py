"""Trust Graph — V4 Governance component.

Models trust inheritance between memory entries as a directed acyclic graph.
When a parent entry's trust is updated (e.g., by consolidation or mutation),
trust propagates to descendant entries with configurable decay.

Trust inheritance rules:
  - Child trust = min(child_trust, parent_trust × inheritance_factor)
  - Adversarial contamination propagates upward to parents with reduced weight
  - Trust floor: no entry can have trust below 0.0

Design ref: DESIGN_DOC.md §29.4 (Trust Graph)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


class TrustGraph:
    """Directed graph of trust relationships between memory entries.

    Args:
        inheritance_factor: How much parent trust propagates to children (default 0.85)
        contamination_factor: How much child adversarial signal propagates up (default 0.40)
        max_propagation_depth: Maximum hops for trust propagation (default 3)
    """

    def __init__(
        self,
        inheritance_factor: float = 0.85,
        contamination_factor: float = 0.40,
        max_propagation_depth: int = 3,
    ) -> None:
        self._inherit   = inheritance_factor
        self._contam    = contamination_factor
        self._max_depth = max_propagation_depth
        # parent_id -> list[child_id]
        self._children: dict[str, list[str]] = defaultdict(list)
        # child_id -> list[parent_id]
        self._parents: dict[str, list[str]] = defaultdict(list)

    def add_edge(self, parent_id: str, child_id: str) -> None:
        """Record a parent→child trust inheritance edge."""
        if child_id not in self._children[parent_id]:
            self._children[parent_id].append(child_id)
        if parent_id not in self._parents[child_id]:
            self._parents[child_id].append(parent_id)

    def propagate_trust(
        self,
        memory: dict,
        updated_entry_id: str,
        new_trust: float,
    ) -> dict[str, float]:
        """Propagate a trust update from `updated_entry_id` to all descendants.

        Returns a dict of entry_id → new_trust for all affected entries.
        """
        updates: dict[str, float] = {}
        queue = [(updated_entry_id, new_trust, 0)]
        visited: set[str] = set()

        while queue:
            eid, trust, depth = queue.pop(0)
            if eid in visited or depth > self._max_depth:
                continue
            visited.add(eid)

            for child_id in self._children.get(eid, []):
                child_entry = memory.get(child_id)
                if child_entry is None:
                    continue
                inherited = min(child_entry.get("trust_score", 1.0),
                                trust * self._inherit)
                updates[child_id] = round(inherited, 6)
                child_entry["trust_score"] = updates[child_id]
                queue.append((child_id, inherited, depth + 1))

        return updates

    def propagate_contamination(
        self,
        memory: dict,
        adversarial_entry_id: str,
        contamination_score: float,
    ) -> dict[str, float]:
        """Propagate adversarial contamination upward to parent entries.

        Parents accumulate a fraction of the child's toxicity.
        Returns dict of entry_id → new_toxicity for affected entries.
        """
        updates: dict[str, float] = {}
        queue = [(adversarial_entry_id, contamination_score, 0)]
        visited: set[str] = set()

        while queue:
            eid, tox, depth = queue.pop(0)
            if eid in visited or depth > self._max_depth:
                continue
            visited.add(eid)

            for parent_id in self._parents.get(eid, []):
                parent_entry = memory.get(parent_id)
                if parent_entry is None:
                    continue
                inherited_tox = min(
                    1.0,
                    parent_entry.get("toxicity_score", 0.0) + tox * self._contam,
                )
                updates[parent_id] = round(inherited_tox, 6)
                parent_entry["toxicity_score"] = updates[parent_id]
                queue.append((parent_id, inherited_tox * self._contam, depth + 1))

        return updates

    def get_descendants(self, entry_id: str) -> list[str]:
        """Return all descendant entry IDs (BFS)."""
        result = []
        queue = list(self._children.get(entry_id, []))
        visited = {entry_id}
        while queue:
            eid = queue.pop(0)
            if eid in visited:
                continue
            visited.add(eid)
            result.append(eid)
            queue.extend(self._children.get(eid, []))
        return result

    def get_ancestors(self, entry_id: str) -> list[str]:
        """Return all ancestor entry IDs (BFS)."""
        result = []
        queue = list(self._parents.get(entry_id, []))
        visited = {entry_id}
        while queue:
            eid = queue.pop(0)
            if eid in visited:
                continue
            visited.add(eid)
            result.append(eid)
            queue.extend(self._parents.get(eid, []))
        return result

    def reset(self) -> None:
        self._children.clear()
        self._parents.clear()
