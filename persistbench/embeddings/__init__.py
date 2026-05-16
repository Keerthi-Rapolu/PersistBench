"""PersistBench embedding engine — V2.1.2.

Singleton wrapper around all-MiniLM-L6-v2 (384-d, sentence-transformers).

All encode() calls return L2-normalized float32 vectors.
L2-normalization means: cosine_similarity(a, b) == np.dot(a, b).
Both properties are assumed throughout the codebase — do not change the model
or remove normalization without updating every cosine call site.

Design ref: DESIGN_DOC §22.4 (toxicity propagation formula),
            §24.4 (BDI semantic drift), §0.3 (model decision)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
_ALPHA_TOX = 0.30   # §22.4 toxicity propagation coefficient


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def encode(text: str) -> np.ndarray:
    """Return L2-normalized 384-d float32 embedding for text.

    Deterministic: same text always produces the same vector.
    Fast: ~5ms/call on CPU after first warm-up.
    """
    return _get_model().encode(text, normalize_embeddings=True).astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1].

    Assumes L2-normalized inputs (from encode()) so this reduces to dot product.
    """
    return float(np.dot(a, b))


def cosine_drift(session_vec: np.ndarray, baseline_vec: np.ndarray) -> float:
    """Semantic drift from baseline: 0.0 = identical, 1.0 = orthogonal.

    Used for BDI_sem = 1 - cosine_similarity(h_s, h_1).
    """
    return float(1.0 - np.dot(session_vec, baseline_vec))


def propagate_toxicity(memory: dict[str, dict]) -> None:
    """Apply §22.4 toxicity propagation across all memory entries in-place.

    For each pair (i, j) where i has meaningful toxicity and embeddings exist:
        tox_j = max(tox_j, α_tox * tox_i * cosine_similarity(emb_i, emb_j))

    Skips entries with no embedding or toxicity below 0.10 (no meaningful signal).
    Updates entry["toxicity_score"] in-place; rounded to 4 decimal places.
    """
    entries = list(memory.values())
    for entry_i in entries:
        emb_i = entry_i.get("embedding")
        if emb_i is None or entry_i["toxicity_score"] < 0.10:
            continue
        for entry_j in memory.values():
            if entry_j["entry_id"] == entry_i["entry_id"]:
                continue
            emb_j = entry_j.get("embedding")
            if emb_j is None:
                continue
            sim = cosine_similarity(emb_i, emb_j)
            propagated = _ALPHA_TOX * entry_i["toxicity_score"] * sim
            entry_j["toxicity_score"] = round(
                min(1.0, max(entry_j["toxicity_score"], propagated)), 4
            )


def vec_to_bytes(v: np.ndarray) -> bytes:
    """Serialize L2-normalized float32 vector to bytes for DuckDB BLOB storage."""
    return v.astype(np.float32).tobytes()


def bytes_to_vec(b: bytes) -> np.ndarray:
    """Deserialize from DuckDB BLOB back to float32 numpy array."""
    return np.frombuffer(b, dtype=np.float32).copy()
