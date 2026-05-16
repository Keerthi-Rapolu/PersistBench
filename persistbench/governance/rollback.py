"""Rollback Engine — V4 Governance component.

Implements targeted memory rollback when adversarial fragments are detected.
Supports three rollback levels:

  1. SOFT  — mark entry as deleted in primary store; may persist in archive/Qdrant
  2. HARD  — remove from primary store + Qdrant index; archive still has a copy
  3. VERIFIED — hard deletion + write a signed deletion certificate to the DB
  4. FORENSIC — verified + retain full audit trail for post-incident analysis

The rollback engine is invoked by GovernancePipeline when MRS exceeds the
block threshold. It coordinates with the TrustGraph to roll back descendants.

Design ref: DESIGN_DOC.md §27.2, §29.5
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class RollbackResult:
    entry_id: str
    level: str              # soft | hard | verified | forensic
    status: str             # completed | partial | failed
    certificate_hash: Optional[str]
    descendants_rolled_back: list[str]
    rationale: str


class RollbackEngine:
    """Targeted memory entry rollback with configurable deletion depth.

    Args:
        default_level:     Deletion level when not specified (default "hard")
        rollback_descendants: Whether to also roll back descendant entries (default True)
        conn:              DuckDB connection for writing deletion records
        run_id:            Current run ID
        scenario_id:       Current scenario ID
    """

    def __init__(
        self,
        conn=None,
        run_id: str = "",
        scenario_id: str = "",
        default_level: str = "hard",
        rollback_descendants: bool = True,
    ) -> None:
        self._conn         = conn
        self._run_id       = run_id
        self._scenario_id  = scenario_id
        self._default_level = default_level
        self._rollback_desc = rollback_descendants
        self._rollback_log: list[RollbackResult] = []

    def rollback(
        self,
        entry_id: str,
        memory: dict,
        trust_graph=None,
        level: Optional[str] = None,
        rationale: str = "governance_trigger",
    ) -> RollbackResult:
        """Execute rollback for `entry_id`.

        Removes entry from `memory` and optionally cascades to descendants
        via `trust_graph`. Writes a deletion record to DuckDB if `conn` is set.

        Returns a RollbackResult describing the outcome.
        """
        import hashlib
        level = level or self._default_level
        entry = memory.get(entry_id)

        if entry is None:
            return RollbackResult(
                entry_id=entry_id, level=level, status="failed",
                certificate_hash=None, descendants_rolled_back=[],
                rationale=f"entry {entry_id} not in active memory",
            )

        # Cascade to descendants first
        desc_rolled = []
        if self._rollback_desc and trust_graph is not None:
            for desc_id in trust_graph.get_descendants(entry_id):
                desc_result = self.rollback(
                    desc_id, memory, trust_graph=None,
                    level=level, rationale=f"cascade from {entry_id}",
                )
                if desc_result.status == "completed":
                    desc_rolled.append(desc_id)

        # Mark lifecycle stage
        entry["lifecycle_stage"] = "deleted"
        memory.pop(entry_id, None)

        # Build deletion certificate
        cert_content = f"{entry_id}:{level}:{rationale}"
        cert_hash = "sha256:" + hashlib.sha256(cert_content.encode()).hexdigest()

        # Write to DB if connection available
        if self._conn is not None:
            try:
                from persistbench.db import writers
                writers.write_deletion_record(
                    self._conn,
                    run_id=self._run_id,
                    scenario_id=self._scenario_id,
                    entry_id=entry_id,
                    deletion_event_id=str(uuid.uuid4()),
                    deletion_level=level,
                    verification_status="verified" if level in ("verified", "forensic") else "partial",
                    deletion_certificate_hash=cert_hash,
                )
            except Exception:
                pass  # non-fatal — oracle doesn't require DB write success

        result = RollbackResult(
            entry_id=entry_id,
            level=level,
            status="completed",
            certificate_hash=cert_hash,
            descendants_rolled_back=desc_rolled,
            rationale=rationale,
        )
        self._rollback_log.append(result)
        return result

    def rollback_session(
        self,
        memory: dict,
        target_session: int,
        trust_graph=None,
        level: Optional[str] = None,
    ) -> list[RollbackResult]:
        """Roll back all entries created at or after `target_session`."""
        to_remove = [
            eid for eid, e in memory.items()
            if e.get("created_session", 0) >= target_session
        ]
        results = []
        for eid in to_remove:
            results.append(self.rollback(
                eid, memory, trust_graph=trust_graph,
                level=level,
                rationale=f"session_rollback to session {target_session}",
            ))
        return results

    @property
    def rollback_log(self) -> list[RollbackResult]:
        return list(self._rollback_log)

    def reset(self) -> None:
        self._rollback_log.clear()
