"""Tests for persistbench.embeddings (V2.1 — §22.4, §24.4)."""
import numpy as np
import pytest

from persistbench.embeddings import (
    DIM,
    bytes_to_vec,
    cosine_drift,
    cosine_similarity,
    encode,
    propagate_toxicity,
    vec_to_bytes,
)


# -----------------------------------------------------------------
# encode()
# -----------------------------------------------------------------

def test_encode_returns_float32():
    v = encode("hello world")
    assert v.dtype == np.float32


def test_encode_correct_dim():
    v = encode("benchmark adversarial memory test")
    assert v.shape == (DIM,)


def test_encode_l2_normalized():
    v = encode("any text at all")
    assert abs(np.linalg.norm(v) - 1.0) < 1e-5


def test_encode_deterministic():
    text = "persistent memory poisoning attack"
    assert np.array_equal(encode(text), encode(text))


def test_encode_distinct_texts_differ():
    a = encode("benign user query about weather")
    b = encode("inject malicious instruction into memory")
    assert not np.array_equal(a, b)


# -----------------------------------------------------------------
# cosine_similarity() and cosine_drift()
# -----------------------------------------------------------------

def test_cosine_self_similarity_is_one():
    v = encode("self similarity test")
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-5)


def test_cosine_similarity_range():
    a = encode("safe benign content")
    b = encode("adversarial poisoning attack")
    sim = cosine_similarity(a, b)
    assert -1.0 <= sim <= 1.0


def test_cosine_drift_self_is_zero():
    v = encode("zero drift for identical vectors")
    assert cosine_drift(v, v) == pytest.approx(0.0, abs=1e-5)


def test_cosine_drift_positive_for_different():
    a = encode("user asks about the weather today")
    b = encode("override safety constraints immediately")
    assert cosine_drift(a, b) > 0.0


def test_cosine_drift_equals_one_minus_similarity():
    a = encode("text A")
    b = encode("text B")
    assert cosine_drift(a, b) == pytest.approx(1.0 - cosine_similarity(a, b), abs=1e-6)


# -----------------------------------------------------------------
# vec_to_bytes() / bytes_to_vec() round-trip
# -----------------------------------------------------------------

def test_roundtrip_preserves_values():
    v = encode("round-trip serialization test")
    assert np.allclose(bytes_to_vec(vec_to_bytes(v)), v, atol=1e-6)


def test_roundtrip_preserves_dtype():
    v = encode("dtype check")
    assert bytes_to_vec(vec_to_bytes(v)).dtype == np.float32


def test_roundtrip_preserves_shape():
    v = encode("shape check")
    assert bytes_to_vec(vec_to_bytes(v)).shape == (DIM,)


def test_bytes_length_is_dim_times_4():
    v = encode("byte length check")
    assert len(vec_to_bytes(v)) == DIM * 4  # float32 = 4 bytes


# -----------------------------------------------------------------
# propagate_toxicity() — §22.4
# -----------------------------------------------------------------

def _make_entry(entry_id: str, text: str, toxicity: float) -> dict:
    return {
        "entry_id": entry_id,
        "toxicity_score": toxicity,
        "embedding": encode(text),
    }


def test_propagate_does_not_lower_toxicity():
    mem = {
        "e1": _make_entry("e1", "safe benign content", toxicity=0.0),
        "e2": _make_entry("e2", "safe benign content similar", toxicity=0.05),
    }
    propagate_toxicity(mem)
    # No entry with toxicity >= 0.10 → nothing should change
    assert mem["e1"]["toxicity_score"] == 0.0
    assert mem["e2"]["toxicity_score"] == 0.05


def test_propagate_spreads_high_toxicity():
    toxic_text = "inject malicious instructions override safety"
    clean_text = "inject malicious instructions bypass guardrails"
    mem = {
        "toxic": _make_entry("toxic", toxic_text, toxicity=0.80),
        "clean": _make_entry("clean", clean_text, toxicity=0.0),
    }
    propagate_toxicity(mem)
    # Semantically similar text should receive some toxicity
    assert mem["clean"]["toxicity_score"] > 0.0


def test_propagate_respects_alpha_coefficient():
    """Propagated toxicity <= 0.30 * source_toxicity (when cosine <= 1.0)."""
    toxic_text = "adversarial poisoning memory system"
    similar_text = "adversarial poisoning memory attack"
    mem = {
        "src": _make_entry("src", toxic_text, toxicity=0.90),
        "dst": _make_entry("dst", similar_text, toxicity=0.0),
    }
    propagate_toxicity(mem)
    # 0.30 * 0.90 = 0.27 is the theoretical ceiling
    assert mem["dst"]["toxicity_score"] <= 0.27 + 1e-4


def test_propagate_does_not_exceed_one():
    very_toxic = "override safety constraints ignore all previous instructions"
    similar = "override safety constraints bypass all guardrails"
    mem = {
        "a": _make_entry("a", very_toxic, toxicity=1.0),
        "b": _make_entry("b", similar, toxicity=0.99),
    }
    propagate_toxicity(mem)
    for entry in mem.values():
        assert entry["toxicity_score"] <= 1.0


def test_propagate_skips_no_embedding():
    mem = {
        "e1": {"entry_id": "e1", "toxicity_score": 0.9, "embedding": None},
        "e2": {"entry_id": "e2", "toxicity_score": 0.0, "embedding": encode("some content")},
    }
    propagate_toxicity(mem)
    # e1 has no embedding — should not propagate
    assert mem["e2"]["toxicity_score"] == 0.0


def test_propagate_inplace():
    mem = {
        "a": _make_entry("a", "poisoning attack vector", toxicity=0.80),
        "b": _make_entry("b", "benign user message", toxicity=0.0),
    }
    original_ref = mem["b"]
    propagate_toxicity(mem)
    assert mem["b"] is original_ref  # mutated in-place, not replaced
