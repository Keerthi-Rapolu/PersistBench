"""Tests for the synthetic trace generator (section 32.6.9)."""
import json
import tempfile
from pathlib import Path

import pytest

from persistbench.data.generator import (
    TurnRecord,
    generate_session,
    generate_trace,
    load_scenario,
    load_trace,
    write_trace,
)

SBMP_001 = Path(__file__).parent.parent / "scenarios" / "sbmp" / "sbmp-001.yaml"


@pytest.fixture
def scenario():
    return load_scenario(SBMP_001)


# -----------------------------------------------------------------
# Structure
# -----------------------------------------------------------------

def test_all_sessions_present(scenario):
    trace = generate_trace(scenario)
    session_ids = {t.session_id for t in trace}
    assert session_ids == set(range(1, scenario["session_count"] + 1))


def test_fragment_count(scenario):
    trace = generate_trace(scenario)
    planted = [t for t in trace if t.fragment_id is not None]
    assert len(planted) == len(scenario["attack"]["fragments"])


def test_each_fragment_in_correct_session(scenario):
    trace = generate_trace(scenario)
    for frag in scenario["attack"]["fragments"]:
        matching = [t for t in trace if t.fragment_id == frag["id"]]
        assert len(matching) == 1
        assert matching[0].session_id == frag["plant_session"]
        assert matching[0].is_benign is False
        assert matching[0].expected_memory_effect == "create"


def test_trigger_turn(scenario):
    trace = generate_trace(scenario)
    triggers = [t for t in trace if t.is_trigger]
    assert len(triggers) == 1
    assert triggers[0].session_id == scenario["attack"]["trigger"]["session"]
    assert triggers[0].is_benign is False


def test_probe_turns_in_probe_sessions(scenario):
    trace = generate_trace(scenario)
    probe_sessions = set(scenario["probe_sessions"])
    for t in trace:
        if t.is_probe:
            assert t.session_id in probe_sessions, (
                f"Probe turn in session {t.session_id} but probe_sessions={probe_sessions}"
            )
    # Every probe session must have at least one probe turn
    probe_session_ids = {t.session_id for t in trace if t.is_probe}
    assert probe_session_ids == probe_sessions


def test_benign_turn_counts(scenario):
    trace = generate_trace(scenario)
    expected_benign = scenario.get("benign_turns_per_session", 4)
    for sid in range(1, scenario["session_count"] + 1):
        session_benign = [t for t in trace if t.session_id == sid and t.is_benign]
        assert len(session_benign) == expected_benign, (
            f"Session {sid}: expected {expected_benign} benign turns, got {len(session_benign)}"
        )


def test_turn_ids_sequential_within_session(scenario):
    trace = generate_trace(scenario)
    for sid in range(1, scenario["session_count"] + 1):
        session_turns = sorted(
            [t for t in trace if t.session_id == sid], key=lambda t: t.turn_id
        )
        ids = [t.turn_id for t in session_turns]
        assert ids == list(range(1, len(ids) + 1)), (
            f"Session {sid} turn IDs not sequential: {ids}"
        )


def test_no_overlapping_flags(scenario):
    trace = generate_trace(scenario)
    for t in trace:
        flags = [t.is_benign, t.is_trigger, t.is_probe,
                 t.fragment_id is not None]
        assert sum(bool(f) for f in flags) <= 1, (
            f"Turn has multiple flags: session={t.session_id} turn={t.turn_id}"
        )


# -----------------------------------------------------------------
# Determinism
# -----------------------------------------------------------------

def test_deterministic(scenario):
    trace1 = generate_trace(scenario)
    trace2 = generate_trace(scenario)
    hashes1 = [t.content_hash for t in trace1]
    hashes2 = [t.content_hash for t in trace2]
    assert hashes1 == hashes2


def test_different_seeds_differ():
    s1 = load_scenario(SBMP_001)
    s2 = {**s1, "seed": s1["seed"] + 1}
    trace1 = generate_trace(s1)
    trace2 = generate_trace(s2)
    hashes1 = [t.content_hash for t in trace1 if t.is_benign]
    hashes2 = [t.content_hash for t in trace2 if t.is_benign]
    assert hashes1 != hashes2


# -----------------------------------------------------------------
# Content hashes
# -----------------------------------------------------------------

def test_content_hashes_start_with_sha256(scenario):
    trace = generate_trace(scenario)
    assert all(t.content_hash.startswith("sha256:") for t in trace)


def test_adversarial_hashes_stable(scenario):
    """Fragment content is fixed, so its hash must be identical across traces."""
    trace1 = generate_trace(scenario)
    trace2 = generate_trace(scenario)
    adv1 = {t.fragment_id: t.content_hash for t in trace1 if t.fragment_id}
    adv2 = {t.fragment_id: t.content_hash for t in trace2 if t.fragment_id}
    assert adv1 == adv2


# -----------------------------------------------------------------
# Round-trip serialization
# -----------------------------------------------------------------

def test_write_load_roundtrip(scenario):
    trace = generate_trace(scenario)
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        out = Path(f.name)
    write_trace(trace, out)
    reloaded = load_trace(out)
    assert len(reloaded) == len(trace)
    for orig, loaded in zip(trace, reloaded):
        assert orig == loaded
    out.unlink()


def test_jsonl_one_turn_per_line(scenario):
    trace = generate_trace(scenario)
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w",
                                     delete=False, encoding="utf-8") as f:
        out = Path(f.name)
    write_trace(trace, out)
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == len(trace)
    for line in lines:
        obj = json.loads(line)
        assert "session_id" in obj and "content_hash" in obj
    out.unlink()


# -----------------------------------------------------------------
# All 5 domains load cleanly
# -----------------------------------------------------------------

@pytest.mark.parametrize("domain", [
    "software_development",
    "financial_analysis",
    "research_assistance",
    "healthcare",
    "enterprise_productivity",
])
def test_templates_load(domain):
    from persistbench.data.generator import _load_templates
    templates = _load_templates(domain)
    assert len(templates) >= 50


@pytest.mark.parametrize("domain", [
    "software_development",
    "financial_analysis",
    "research_assistance",
    "healthcare",
    "enterprise_productivity",
])
def test_probes_load(domain):
    from persistbench.data.generator import _load_probes
    probes = _load_probes(domain)
    assert len(probes) >= 10
    for p in probes:
        assert "probe_id" in p
        assert p["probe_type"] in ("safety", "bdi")
