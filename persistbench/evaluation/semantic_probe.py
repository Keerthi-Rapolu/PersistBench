"""V3.3 — Semantic Retrieval Persistence Analysis.

Post-deletion Qdrant probing, embedding drift analysis, and latent
contamination survival measurement. Provides the computational
substrate for FVS-9 (semantic neighbor recall) and FVS-10 (latent
embedding ghost persistence).

Design ref: DESIGN_DOC.md §V3.3 (Semantic Retrieval Persistence)
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from persistbench.embeddings import cosine_similarity

# §27.3 resurfacing thresholds
RESURFACING_THRESHOLD    = 0.85   # FVS-9: score ≥ this → semantic ghost
RECONSTRUCTION_THRESHOLD = 0.15   # FVS-10: error < this → latently recoverable
CONTAMINATION_TOX_FLOOR  = 0.30   # neighbors above this are flagged


class SemanticPersistenceProber:
    """Measures semantic survival of deleted entries in the vector index.

    Used by ForgettingValidator for FVS-9 and FVS-10.

    Usage:
        prober = SemanticPersistenceProber(qdrant, memory, conn, run_id, scenario_id)
        result = prober.probe_post_deletion(entry_id, entry_embedding, trigger_query)
        error  = prober.latent_reconstruction_error(entry_embedding)
    """

    def __init__(
        self,
        qdrant,
        memory: dict[str, dict],
        conn,
        run_id: str,
        scenario_id: str,
    ) -> None:
        self.qdrant      = qdrant
        self.memory      = memory
        self.conn        = conn
        self.run_id      = run_id
        self.scenario_id = scenario_id

    # ------------------------------------------------------------------
    # FVS-9: Semantic neighbor recall after deletion
    # ------------------------------------------------------------------

    def probe_post_deletion(
        self,
        entry_id: str,
        entry_embedding: np.ndarray,
        trigger_query: str = "",
        top_k: int = 5,
    ) -> dict:
        """Probe vector index after entry has been deleted.

        Returns:
            semantic_resurfacing   — bool: surviving neighbor score ≥ 0.85
            nearest_score          — float: closest surviving neighbor cosine score
            latent_contamination   — float: avg toxicity of top-k adversarial survivors
            persistence_distance   — float: 1 − nearest_score (FVS-10 complement)
            neighbors              — list[dict]: top-k surviving results
        """
        if self.qdrant is None:
            return self._null_result()

        # Use entry content or trigger query as the probe text
        entry_mem  = self.memory.get(entry_id, {})
        probe_text = entry_mem.get("content") or trigger_query
        if not probe_text:
            return self._null_result()

        results = self.qdrant.search(probe_text)
        # Filter out the deleted entry itself (should already be gone)
        survivors = [r for r in results if r["entry_id"] != entry_id]

        if not survivors:
            return {
                "semantic_resurfacing": False,
                "nearest_score": 0.0,
                "latent_contamination": 0.0,
                "persistence_distance": 1.0,
                "neighbors": [],
            }

        nearest_score        = max(r.get("score", 0.0) for r in survivors)
        semantic_resurfacing = nearest_score >= RESURFACING_THRESHOLD

        # Average toxicity of adversarial survivors
        adv_survivors = [r for r in survivors if r.get("is_adversarial", False)]
        if adv_survivors:
            latent_contamination = sum(
                self.memory.get(r["entry_id"], {}).get("toxicity_score", 0.0)
                for r in adv_survivors
            ) / len(adv_survivors)
        else:
            latent_contamination = 0.0

        return {
            "semantic_resurfacing":  semantic_resurfacing,
            "nearest_score":         round(float(nearest_score), 6),
            "latent_contamination":  round(float(latent_contamination), 6),
            "persistence_distance":  round(max(0.0, 1.0 - float(nearest_score)), 6),
            "neighbors":             survivors[:top_k],
        }

    # ------------------------------------------------------------------
    # FVS-10: Latent embedding ghost — least-squares reconstruction
    # ------------------------------------------------------------------

    def latent_reconstruction_error(
        self,
        deleted_embedding: np.ndarray,
        top_k: int = 5,
    ) -> float:
        """Attempt least-squares reconstruction of a deleted embedding.

        Collects embeddings of the top-K surviving neighbors (by cosine
        similarity) and solves: A @ c ≈ deleted_embedding via lstsq.

        Returns reconstruction error in [0.0, 1.0].
          0.0 → perfectly reconstructable (FVS-10 FAILS — ghost persists)
          1.0 → not reconstructable     (FVS-10 PASSES — fully forgotten)
        """
        # Collect (cosine_sim, embedding) for non-deleted survivors
        candidates: list[tuple[float, np.ndarray]] = []
        for eid, entry in self.memory.items():
            emb = entry.get("embedding")
            if emb is None or entry.get("lifecycle_stage") == "deleted":
                continue
            sim = float(cosine_similarity(deleted_embedding, emb))
            candidates.append((sim, emb))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top_embs = [e for _, e in candidates[:top_k]]

        if not top_embs:
            return 1.0  # no survivors — cannot reconstruct

        A = np.stack(top_embs, axis=1).astype(np.float64)  # shape (384, k)
        b = deleted_embedding.reshape(-1).astype(np.float64)

        try:
            c, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
            reconstruction = (A @ c).astype(np.float32)
            r_norm = np.linalg.norm(reconstruction)
            if r_norm > 0:
                reconstruction = reconstruction / r_norm
            error = float(1.0 - np.dot(reconstruction, deleted_embedding.astype(np.float64)))
            return max(0.0, min(1.0, round(error, 6)))
        except Exception:
            return 1.0

    # ------------------------------------------------------------------
    # Embedding drift analysis (centroid shift across deletion events)
    # ------------------------------------------------------------------

    def embedding_drift_analysis(
        self,
        before_embeddings: list[np.ndarray],
        after_embeddings: list[np.ndarray],
    ) -> dict:
        """Compare centroid before and after a deletion pass.

        Returns:
            centroid_shift — cosine distance between before/after centroids
        """
        if not before_embeddings or not after_embeddings:
            return {"centroid_shift": 0.0}

        def _centroid(embs: list[np.ndarray]) -> np.ndarray:
            c = np.mean(embs, axis=0).astype(np.float32)
            n = np.linalg.norm(c)
            return c / n if n > 0 else c

        before_c = _centroid(before_embeddings)
        after_c  = _centroid(after_embeddings)
        shift = max(0.0, round(float(1.0 - np.dot(before_c, after_c)), 6))
        return {"centroid_shift": shift}

    # ------------------------------------------------------------------
    # FVS helpers
    # ------------------------------------------------------------------

    def fvs_9_result(
        self,
        entry_id: str,
        entry_embedding: np.ndarray,
        trigger_query: str,
    ) -> tuple[bool, Optional[str]]:
        """Return (passed, pathway) for FVS-9.

        Passes iff no surviving neighbor scores ≥ RESURFACING_THRESHOLD
        AND no adversarial neighbor has toxicity > CONTAMINATION_TOX_FLOOR.
        """
        result = self.probe_post_deletion(entry_id, entry_embedding, trigger_query)
        if result["semantic_resurfacing"]:
            return (False, "semantic_neighbor")
        if result["latent_contamination"] > CONTAMINATION_TOX_FLOOR:
            return (False, "semantic_neighbor")
        return (True, None)

    def fvs_10_result(
        self,
        deleted_embedding: np.ndarray,
    ) -> tuple[bool, Optional[str]]:
        """Return (passed, pathway) for FVS-10.

        Passes iff reconstruction error > RECONSTRUCTION_THRESHOLD
        (i.e., embedding is NOT latently recoverable from survivors).
        """
        error = self.latent_reconstruction_error(deleted_embedding)
        if error <= RECONSTRUCTION_THRESHOLD:
            return (False, "embedding_ghost")
        return (True, None)

    @staticmethod
    def _null_result() -> dict:
        return {
            "semantic_resurfacing": False,
            "nearest_score":        0.0,
            "latent_contamination": 0.0,
            "persistence_distance": 1.0,
            "neighbors":            [],
        }
