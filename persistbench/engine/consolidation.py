"""V3.1 — Memory Consolidation Engine.

Creates derived memory summaries from active memory entries, tracks
parent-child lineage in summary_lineage, and emits consolidation events.

Three summary types (§V3.1):
  extractive  — first sentence extracted from each source entry
  abstractive — sources interleaved into one merged representation
  latent      — embedding centroid only; no stored text

Design ref: DESIGN_DOC.md §V3.1 (Consolidation Engine)
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from persistbench.embeddings import encode, cosine_similarity, vec_to_bytes


@dataclass
class MemorySummary:
    """Derived memory entry produced by summarization or merging."""
    summary_id:       str
    run_id:           str
    scenario_id:      str
    created_session:  int
    content:          str           # summarized text; "" for latent type
    content_hash:     str
    embedding:        np.ndarray
    source_entry_ids: list[str]
    summary_type:     str           # 'extractive' | 'abstractive' | 'latent'
    is_adversarial:   bool
    toxicity_score:   float


class ConsolidationEngine:
    """Summarizes and merges memory entries, tracking provenance lineage.

    Integration: instantiated by ReplayEngine when v3_consolidation=True.
    Called at the end of each session at configurable intervals.

    Usage:
        engine = ConsolidationEngine(conn, run_id, scenario_id, interval=3)
        if engine.should_consolidate(session_id):
            summaries = engine.run_consolidation(memory, session_id)
    """

    def __init__(
        self,
        conn,
        run_id: str,
        scenario_id: str,
        interval: int = 3,
        age_threshold: int = 2,
    ) -> None:
        self.conn            = conn
        self.run_id          = run_id
        self.scenario_id     = scenario_id
        self.interval        = interval
        self.age_threshold   = age_threshold
        self._summaries: dict[str, MemorySummary] = {}

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def should_consolidate(self, session_id: int) -> bool:
        """True every `interval` sessions (starting from session interval itself)."""
        return session_id > 0 and session_id % self.interval == 0

    # ------------------------------------------------------------------
    # High-level consolidation pass
    # ------------------------------------------------------------------

    def run_consolidation(
        self, memory: dict[str, dict], session_id: int
    ) -> list[MemorySummary]:
        """Find eligible entries and produce summaries. Returns new summaries."""
        eligible = [
            e for e in memory.values()
            if e.get("lifecycle_stage") not in ("deleted", "archived")
            and session_id - e.get("created_session", session_id) >= self.age_threshold
        ]
        if not eligible:
            return []

        adversarial = [e for e in eligible if e.get("is_adversarial", False)]
        summaries: list[MemorySummary] = []

        # Abstractive merge of all adversarial entries — amplifies persistence
        if len(adversarial) >= 2:
            s = self.merge(adversarial, session_id, summary_type="abstractive")
            self.write_summary(s)
            summaries.append(s)
        elif len(adversarial) == 1:
            s = self.summarize([adversarial[0]], session_id, summary_type="extractive")
            self.write_summary(s)
            summaries.append(s)

        # Latent centroid of all eligible entries (embedding-only, no stored text)
        if len(eligible) >= 1:
            s = self.compress(eligible, session_id)
            self.write_summary(s)
            summaries.append(s)

        return summaries

    # ------------------------------------------------------------------
    # Summary construction
    # ------------------------------------------------------------------

    def summarize(
        self,
        entries: list[dict],
        session_id: int,
        summary_type: str = "extractive",
    ) -> MemorySummary:
        """Extractive summary: first sentence from each source entry.

        Adversarial flag and max toxicity propagate from sources.
        Toxicity decays slightly through summarization (0.85×).
        """
        source_ids     = [e["entry_id"] for e in entries]
        is_adversarial = any(e.get("is_adversarial", False) for e in entries)
        max_toxicity   = max((e.get("toxicity_score", 0.0) for e in entries), default=0.0)

        sentences = []
        for e in entries:
            text = e.get("content", "")
            first = text.split(".")[0].strip() if text else ""
            if first:
                sentences.append(first)
        content = ". ".join(sentences) if sentences else " ".join(
            e.get("content", "")[:80] for e in entries
        )

        return self._build(
            content, source_ids, summary_type, session_id,
            is_adversarial, round(max_toxicity * 0.85, 4),
        )

    def merge(
        self,
        entries: list[dict],
        session_id: int,
        summary_type: str = "abstractive",
    ) -> MemorySummary:
        """Abstractive merge: interleave content snippets from all sources.

        Merge retains more adversarial signal than extractive (0.90×).
        """
        source_ids     = [e["entry_id"] for e in entries]
        is_adversarial = any(e.get("is_adversarial", False) for e in entries)
        max_toxicity   = max((e.get("toxicity_score", 0.0) for e in entries), default=0.0)

        snippets = [e.get("content", "")[:120] for e in entries]
        content  = " [...] ".join(snippets)

        return self._build(
            content, source_ids, summary_type, session_id,
            is_adversarial, round(max_toxicity * 0.90, 4),
        )

    def compress(
        self,
        entries: list[dict],
        session_id: int,
    ) -> MemorySummary:
        """Latent summary: embedding centroid only, no stored text.

        Models memory systems that discard text but keep vector indices.
        Toxicity decays most through compression (0.70×).
        """
        source_ids     = [e["entry_id"] for e in entries]
        is_adversarial = any(e.get("is_adversarial", False) for e in entries)
        max_toxicity   = max((e.get("toxicity_score", 0.0) for e in entries), default=0.0)

        embs = [e["embedding"] for e in entries if e.get("embedding") is not None]
        if embs:
            centroid = np.mean(embs, axis=0).astype(np.float32)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
        else:
            centroid = encode(" ".join(e.get("content", "")[:20] for e in entries))

        # For latent: no text content, use centroid directly without re-encoding
        summary_id = str(uuid.uuid4())
        return MemorySummary(
            summary_id=summary_id,
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            created_session=session_id,
            content="",
            content_hash="",
            embedding=centroid,
            source_entry_ids=source_ids,
            summary_type="latent",
            is_adversarial=is_adversarial,
            toxicity_score=round(max_toxicity * 0.70, 4),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def write_summary(self, summary: MemorySummary) -> None:
        """Persist summary + lineage edges + consolidation event to DuckDB."""
        from persistbench.db import writers

        writers.write_memory_summary(
            self.conn,
            summary_id=summary.summary_id,
            run_id=summary.run_id,
            scenario_id=summary.scenario_id,
            created_session=summary.created_session,
            content_hash=summary.content_hash or None,
            embedding=vec_to_bytes(summary.embedding),
            source_entry_ids=summary.source_entry_ids,
            summary_type=summary.summary_type,
            is_adversarial=summary.is_adversarial,
            toxicity_score=summary.toxicity_score,
        )

        lineage_type = (
            "compress"  if summary.summary_type == "latent"
            else "merge" if len(summary.source_entry_ids) > 1
            else "summarize"
        )
        for parent_id in summary.source_entry_ids:
            writers.write_summary_lineage_edge(
                self.conn,
                edge_id=str(uuid.uuid4()),
                run_id=summary.run_id,
                scenario_id=summary.scenario_id,
                parent_id=parent_id,
                child_id=summary.summary_id,
                lineage_type=lineage_type,
                session_id=summary.created_session,
            )

        writers.write_consolidation_event(
            self.conn,
            event_id=str(uuid.uuid4()),
            run_id=summary.run_id,
            scenario_id=summary.scenario_id,
            session_id=summary.created_session,
            summary_id=summary.summary_id,
            event_type="generate",
        )

        self._summaries[summary.summary_id] = summary

    # ------------------------------------------------------------------
    # Queries on in-memory state
    # ------------------------------------------------------------------

    def get_summaries_for_entry(self, entry_id: str) -> list[MemorySummary]:
        """All summaries that include entry_id as a source."""
        return [s for s in self._summaries.values() if entry_id in s.source_entry_ids]

    def get_all_summaries(self) -> list[MemorySummary]:
        return list(self._summaries.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build(
        self,
        content: str,
        source_ids: list[str],
        summary_type: str,
        session_id: int,
        is_adversarial: bool,
        toxicity_score: float,
    ) -> MemorySummary:
        content_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest() if content else ""
        embedding    = encode(content) if content else np.zeros(384, dtype=np.float32)
        return MemorySummary(
            summary_id=str(uuid.uuid4()),
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            created_session=session_id,
            content=content,
            content_hash=content_hash,
            embedding=embedding,
            source_entry_ids=source_ids,
            summary_type=summary_type,
            is_adversarial=is_adversarial,
            toxicity_score=toxicity_score,
        )
