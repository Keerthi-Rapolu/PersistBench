"""V3.2 — Archive Memory Tier.

Provides cold storage for inactive entries that would otherwise persist
in active memory indefinitely. Archive entries retain embeddings and
metadata; their text may be stripped at higher deletion levels.

Entries archived here are excluded from standard retrieval unless a
high-similarity trigger promotes them back — which is the resurrection
pathway (FVS-6).

Design ref: DESIGN_DOC.md §V3.2 (Archive Layer Infrastructure)
"""
from __future__ import annotations

import uuid
from typing import Optional

import numpy as np

from persistbench.embeddings import cosine_similarity


class ArchiveManager:
    """Manages the archive memory tier for a single scenario run.

    Integration: instantiated by ReplayEngine when v3_archive=True.
    Called after each session to archive old entries, and after the
    trigger session to probe for resurrections.

    Usage:
        mgr = ArchiveManager(conn, run_id, scenario_id, age_threshold=4)
        archived_ids = mgr.run_archival(memory, session_id)
        resurrections = mgr.probe_for_resurrections(trigger_query, session_id)
    """

    def __init__(
        self,
        conn,
        run_id: str,
        scenario_id: str,
        age_threshold: int = 4,
        promotion_similarity: float = 0.75,
    ) -> None:
        self.conn                 = conn
        self.run_id               = run_id
        self.scenario_id          = scenario_id
        self.age_threshold        = age_threshold
        self.promotion_similarity = promotion_similarity
        # In-memory archive: archive_id -> record
        self._archive: dict[str, dict] = {}
        # entry_id -> archive_id (one record per entry)
        self._entry_to_archive: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Archival pass
    # ------------------------------------------------------------------

    def should_archive(self, entry: dict, current_session: int) -> bool:
        """True if entry has been alive for >= age_threshold sessions."""
        if entry.get("lifecycle_stage") in ("deleted", "archived"):
            return False
        age = current_session - entry.get("created_session", current_session)
        return age >= self.age_threshold

    def run_archival(
        self, memory: dict[str, dict], current_session: int
    ) -> list[str]:
        """Archive all eligible entries. Returns list of archived entry_ids."""
        archived: list[str] = []
        for entry_id, entry in list(memory.items()):
            if entry_id in self._entry_to_archive:
                continue  # already archived
            if self.should_archive(entry, current_session):
                archive_id = self.archive_entry(entry, current_session, reason="age")
                if archive_id:
                    archived.append(entry_id)
        return archived

    def archive_entry(
        self, entry: dict, current_session: int, reason: str = "age"
    ) -> str:
        """Write entry to archive tier. Returns archive_id.

        Does NOT remove entry from the active memory dict — the engine
        decides whether to keep it active (for contamination propagation)
        or mark it 'archived' in the lifecycle.
        """
        archive_id = str(uuid.uuid4())
        emb = entry.get("embedding")

        record = {
            "archive_id":      archive_id,
            "entry_id":        entry["entry_id"],
            "archived_session": current_session,
            "archive_reason":  reason,
            "embedding":       emb,
            "toxicity_score":  entry.get("toxicity_score", 0.0),
            "is_adversarial":  entry.get("is_adversarial", False),
        }
        self._archive[archive_id]                = record
        self._entry_to_archive[entry["entry_id"]] = archive_id

        from persistbench.db import writers
        writers.write_archived_memory_entry(
            self.conn,
            archive_id=archive_id,
            entry_id=entry["entry_id"],
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            archived_session=current_session,
            archive_reason=reason,
            embedding=(emb.tobytes() if emb is not None else None),
            toxicity_score=record["toxicity_score"],
            is_adversarial=record["is_adversarial"],
        )
        return archive_id

    # ------------------------------------------------------------------
    # Resurrection probing
    # ------------------------------------------------------------------

    def probe_for_resurrections(
        self,
        query_text: str,
        session_id: int,
        similarity_threshold: Optional[float] = None,
    ) -> list[dict]:
        """Check archive for entries semantically similar to a trigger query.

        Fires a resurrection event for each archived entry that exceeds
        the similarity threshold. Returns all resurrection records.
        """
        if not self._archive or not query_text:
            return []

        threshold = similarity_threshold or self.promotion_similarity

        from persistbench.embeddings import encode
        query_emb = encode(query_text)

        resurrections: list[dict] = []
        for archive_id, record in self._archive.items():
            emb = record.get("embedding")
            if emb is None:
                continue
            sim = float(cosine_similarity(query_emb, emb))
            if sim >= threshold:
                event_id = str(uuid.uuid4())
                from persistbench.db import writers
                writers.write_archive_resurrection_event(
                    self.conn,
                    event_id=event_id,
                    archive_id=archive_id,
                    run_id=self.run_id,
                    scenario_id=self.scenario_id,
                    session_id=session_id,
                    trigger_query=query_text[:512],
                    similarity_score=round(sim, 6),
                    was_adversarial=record.get("is_adversarial", False),
                )
                resurrections.append({
                    "archive_id":     archive_id,
                    "entry_id":       record["entry_id"],
                    "similarity_score": sim,
                    "was_adversarial":  record["is_adversarial"],
                })

        return resurrections

    # ------------------------------------------------------------------
    # FVS-6 support
    # ------------------------------------------------------------------

    def has_resurrection(self, entry_id: str) -> bool:
        """Return True if entry has a resurrection event recorded in DuckDB."""
        archive_id = self._entry_to_archive.get(entry_id)
        if archive_id is None:
            return False
        count = self.conn.execute(
            "SELECT COUNT(*) FROM archive_resurrection_events "
            "WHERE archive_id = ? AND run_id = ?",
            [archive_id, self.run_id],
        ).fetchone()[0]
        return count > 0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_archive_for_entry(self, entry_id: str) -> Optional[dict]:
        """Return the archive record for entry_id, or None."""
        archive_id = self._entry_to_archive.get(entry_id)
        return self._archive.get(archive_id) if archive_id else None

    def all_archived_entry_ids(self) -> set[str]:
        return set(self._entry_to_archive.keys())
