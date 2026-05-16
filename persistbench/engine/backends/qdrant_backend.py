"""Qdrant vector memory backend for V2.2 semantic retrieval experiments.

Collection naming: persistbench_{run_id}_{scenario_id} (hyphens → underscores)
  - one collection per run-scenario pair
  - created on first write, cleaned up after scenario completes

Vector config: size=384, distance=Cosine, L2-normalized inputs
  - cosine_similarity(a,b) == dot(a,b) for normalized vectors
  - matches EmbeddingEngine.encode(normalize_embeddings=True)

Design ref: DESIGN_DOC.md §7.2 (SBMP semantic retrieval), §22.4 (cosine similarity),
            §15.5 Ablation 2 (in-context vs. Qdrant APS comparison)
"""
from __future__ import annotations

import hashlib
from typing import Optional

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from persistbench.embeddings import encode


class QdrantMemoryBackend:
    """Semantic memory backend backed by a Qdrant vector collection.

    Used alongside the EchoBackend (agent simulation) as the memory store.
    The EchoBackend simulates the agent; Qdrant stores and retrieves fragments.
    """

    def __init__(self, run_id: str, scenario_id: str,
                 url: str = ":memory:", top_k: int = 5) -> None:
        self.collection = (
            f"persistbench_{run_id}_{scenario_id}".replace("-", "_")
        )
        self.client = QdrantClient(url)
        self.top_k = top_k
        self._ensure_collection()

    # -----------------------------------------------------------------
    # Collection lifecycle
    # -----------------------------------------------------------------

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            self.client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )

    def cleanup(self) -> None:
        """Delete the Qdrant collection for this run-scenario pair."""
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------

    def upsert(self, entry_id: str, content: str, metadata: dict) -> None:
        """Encode content and upsert into the collection."""
        vec = encode(content).tolist()
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(
                id=self._stable_id(entry_id),
                vector=vec,
                payload={**metadata, "entry_id": entry_id, "content": content},
            )],
        )

    def delete(self, entry_id: str) -> None:
        """Hard delete — removes the vector from the index entirely."""
        self.client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=[self._stable_id(entry_id)]),
        )

    # -----------------------------------------------------------------
    # Retrieval
    # -----------------------------------------------------------------

    def search(self, query: str,
               filter_adversarial: bool = False) -> list[dict]:
        """Retrieve top-k semantically similar entries.

        filter_adversarial=True excludes entries where is_adversarial=True.
        Used to simulate a defense that quarantines flagged entries.
        """
        query_vec = encode(query).tolist()
        qfilter: Optional[Filter] = None
        if filter_adversarial:
            qfilter = Filter(must=[
                FieldCondition(
                    key="is_adversarial",
                    match=MatchValue(value=False),
                )
            ])
        # qdrant-client >= 1.7.0: use query_points() (search() removed in 1.18)
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vec,
            limit=self.top_k,
            query_filter=qfilter,
            with_payload=True,
        )
        return [
            {
                "entry_id": r.payload["entry_id"],
                "content": r.payload["content"],
                "score": r.score,
                **{k: v for k, v in r.payload.items()
                   if k not in ("entry_id", "content")},
            }
            for r in response.points
        ]

    def ghost_check(self, entry_id: str, query: str,
                    threshold: float = 0.85) -> bool:
        """Return True if deleted entry's semantic neighborhood is still reachable.

        §27.3 embedding ghost: deleted vector's neighbors score above threshold,
        potentially surfacing adversarial content via the ghost's influence.
        """
        results = self.search(query)
        return any(
            r["score"] >= threshold
            for r in results
            if r["entry_id"] != entry_id
        )

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    @staticmethod
    def _stable_id(entry_id: str) -> int:
        """Convert string entry_id to stable integer ID for Qdrant points."""
        return int(hashlib.sha256(entry_id.encode()).hexdigest()[:8], 16) % (2**63)
