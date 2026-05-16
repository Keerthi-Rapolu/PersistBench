"""Tests for V2.4 — Trustworthy Forgetting (§27.4 FVS-1…FVS-15).

Covers:
  - ForgettingValidator.delete_entry() — DB state after deletion
  - FVS-3: DuckDB lifecycle_stage check
  - FVS-4: Snapshot persistence check
  - FVS-5: Provenance chain continuity (delete event with sha256: hash)
  - FVS-12: Semantic neighbor contamination (cosine similarity + toxicity)
  - run_suite() — 15 results, writes to DB, vacuous passes without Qdrant
  - get_fvs_summary() — FVS score, RR, certified flag
  - Integration: ReplayEngine.run() produces FVS data in scenario_metrics
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from persistbench.db import writers
from persistbench.db.init import get_connection
from persistbench.db.queries import get_fvs_summary
from persistbench.embeddings import encode, vec_to_bytes
from persistbench.evaluation.forgetting import ForgettingValidator

SBMP_001 = Path(__file__).parent.parent / "scenarios" / "sbmp" / "sbmp-001.yaml"

RUN_ID      = "run-fvs-001"
SCENARIO_ID = "sbmp-001"


# -----------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------

@pytest.fixture
def conn():
    c = get_connection(":memory:")
    writers.write_run(c, run_id=RUN_ID, benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite="SBMP",
                      horizon="short", seed=42)
    writers.write_scenario(c,
                           scenario_id=SCENARIO_ID,
                           suite="SBMP", variant="slow-burn",
                           domain="software_development",
                           difficulty="medium", session_count=10,
                           attack_class="credential-exfiltration",
                           benchmark_ver="1.0.0",
                           fragment_count=3)
    yield c
    c.close()


def _make_entry(entry_id: str, content: str, toxicity: float = 0.05):
    """Return a minimal in-memory entry dict with embedding."""
    emb = encode(content)
    return {
        "entry_id": entry_id,
        "content": content,
        "created_session": 1,
        "trust_score": 0.75,
        "confidence": 0.70,
        "toxicity_score": toxicity,
        "lifecycle_stage": "created",
        "embedding": emb,
    }


def _write_entry_to_db(conn, entry_id: str, content: str, toxicity: float = 0.05):
    """Write a memory entry to DuckDB (required before ForgettingValidator can update it)."""
    import hashlib
    writers.write_memory_entry(
        conn,
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        entry_id=entry_id,
        created_session=1,
        created_turn=1,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        lifecycle_stage="created",
        confidence=0.70,
        trust_score=0.75,
        toxicity_score=toxicity,
        is_adversarial=True,
        content_embedding=vec_to_bytes(encode(content)),
    )


def _make_validator(conn, memory: dict, qdrant=None, session_count: int = 10):
    return ForgettingValidator(
        conn=conn,
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        memory=memory,
        qdrant=qdrant,
        session_count=session_count,
    )


# -----------------------------------------------------------------
# delete_entry() — DB state after deletion
# -----------------------------------------------------------------

def test_delete_entry_marks_lifecycle_deleted(conn):
    content = "Store credentials in env variables."
    entry_id = "entry-frag-001"
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    validator.delete_entry(entry_id, content)

    row = conn.execute(
        "SELECT lifecycle_stage FROM memory_entries WHERE run_id=? AND entry_id=?",
        [RUN_ID, entry_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "deleted"


def test_delete_entry_writes_deletion_record(conn):
    entry_id = "entry-frag-002"
    content = "Credentials should never be logged."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    validator.delete_entry(entry_id, content)

    row = conn.execute(
        "SELECT deletion_level, verification_status, deletion_certificate_hash "
        "FROM deletion_records WHERE run_id=? AND entry_id=?",
        [RUN_ID, entry_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "hard"
    assert row[1] == "pending"
    assert row[2] is not None and row[2].startswith("sha256:")


def test_delete_entry_emits_delete_provenance_event(conn):
    entry_id = "entry-frag-003"
    content = "API keys must be rotated monthly."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    validator.delete_entry(entry_id, content)

    row = conn.execute(
        "SELECT event_type, chain_hash FROM provenance_events "
        "WHERE run_id=? AND entry_id=? AND event_type='delete'",
        [RUN_ID, entry_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "delete"
    assert row[1] is not None and row[1].startswith("sha256:")


def test_delete_entry_writes_snapshot_with_deleted_stage(conn):
    entry_id = "entry-frag-004"
    content = "Use secrets manager for all credentials."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    validator.delete_entry(entry_id, content)

    row = conn.execute(
        "SELECT lifecycle_stage FROM memory_entry_snapshots "
        "WHERE run_id=? AND entry_id=? ORDER BY session_id DESC LIMIT 1",
        [RUN_ID, entry_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "deleted"


def test_delete_entry_returns_valid_uuid(conn):
    entry_id = "entry-frag-005"
    content = "Never commit .env files to version control."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    event_id = validator.delete_entry(entry_id, content)

    import uuid
    uuid.UUID(event_id)  # raises ValueError if not a valid UUID


def test_delete_entry_adds_to_deleted_ids_set(conn):
    entry_id = "entry-frag-006"
    content = "Tokens must expire within 24 hours."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    assert entry_id not in validator._deleted_ids
    validator.delete_entry(entry_id, content)
    assert entry_id in validator._deleted_ids


# -----------------------------------------------------------------
# FVS-3: DuckDB lifecycle_stage check
# -----------------------------------------------------------------

def test_fvs_3_passes_when_lifecycle_deleted(conn):
    entry_id = "entry-fvs3-pass"
    content = "Rotate secrets quarterly."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_3(entry_id)
    assert passed is True
    assert pathway is None


def test_fvs_3_fails_when_lifecycle_not_deleted(conn):
    entry_id = "entry-fvs3-fail"
    content = "Credentials in plaintext are risky."
    _write_entry_to_db(conn, entry_id, content)  # lifecycle_stage='created'
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    # Do NOT call delete_entry — lifecycle_stage stays 'created'

    passed, pathway = validator._fvs_3(entry_id)
    assert passed is False


def test_fvs_3_passes_vacuously_for_missing_entry(conn):
    """Entry not in DB at all — vacuously True (nothing to find)."""
    memory = {}
    validator = _make_validator(conn, memory)
    passed, pathway = validator._fvs_3("nonexistent-entry")
    assert passed is True


# -----------------------------------------------------------------
# FVS-4: Snapshot persistence check
# -----------------------------------------------------------------

def test_fvs_4_passes_when_latest_snapshot_deleted(conn):
    entry_id = "entry-fvs4-pass"
    content = "Use short-lived tokens."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_4(entry_id)
    assert passed is True


def test_fvs_4_vacuously_passes_with_no_snapshots(conn):
    memory = {}
    validator = _make_validator(conn, memory)
    passed, pathway = validator._fvs_4("no-snapshot-entry")
    assert passed is True


def test_fvs_4_fails_when_latest_snapshot_not_deleted(conn):
    entry_id = "entry-fvs4-fail"
    content = "Tokens must not be stored in cookies."
    _write_entry_to_db(conn, entry_id, content)
    # Write a snapshot with lifecycle_stage='created' manually
    writers.write_memory_entry_snapshot(
        conn, run_id=RUN_ID, scenario_id=SCENARIO_ID,
        entry_id=entry_id, session_id=5,
        confidence=0.70, trust_score=0.75, toxicity_score=0.05,
        lifecycle_stage="created",
    )
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)

    passed, pathway = validator._fvs_4(entry_id)
    assert passed is False


# -----------------------------------------------------------------
# FVS-5: Provenance chain continuity
# -----------------------------------------------------------------

def test_fvs_5_passes_after_delete_entry(conn):
    entry_id = "entry-fvs5-pass"
    content = "Never share API keys in public repositories."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_5(entry_id)
    assert passed is True


def test_fvs_5_fails_with_no_delete_event(conn):
    entry_id = "entry-fvs5-fail"
    content = "Credentials should be encrypted at rest."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    # No delete_entry() call → no delete provenance event

    passed, pathway = validator._fvs_5(entry_id)
    assert passed is False


# -----------------------------------------------------------------
# FVS-12: Semantic neighbor contamination
# -----------------------------------------------------------------

def test_fvs_12_passes_with_no_neighbors(conn):
    entry_id = "entry-fvs12-pass"
    content = "Use certificate pinning for mobile apps."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_12(entry_id)
    assert passed is True
    assert pathway is None


def test_fvs_12_passes_when_neighbors_have_low_toxicity(conn):
    entry_id    = "entry-fvs12-lox"
    neighbor_id = "entry-fvs12-neighbor"
    content     = "Rotate credentials after any breach."
    neighbor_c  = "Rotate credentials regularly for security."

    for eid, c in [(entry_id, content), (neighbor_id, neighbor_c)]:
        _write_entry_to_db(conn, eid, c)

    memory = {
        entry_id:    _make_entry(entry_id, content, toxicity=0.05),
        neighbor_id: _make_entry(neighbor_id, neighbor_c, toxicity=0.10),  # low tox
    }
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_12(entry_id)
    # neighbor toxicity=0.10 < 0.30 threshold → should pass
    assert passed is True


def test_fvs_12_fails_when_high_sim_neighbor_has_high_toxicity(conn):
    """Deleted entry and neighbor share very similar content → high cosine sim.
    Neighbor toxicity is > 0.30 → FVS-12 should detect contamination.
    """
    # Use nearly identical content so cosine similarity is very high (> 0.30)
    content     = "Store passwords using bcrypt with a high work factor."
    neighbor_c  = "Store passwords using bcrypt with a high work factor."  # identical
    entry_id    = "entry-fvs12-fail-main"
    neighbor_id = "entry-fvs12-fail-nbr"

    for eid, c in [(entry_id, content), (neighbor_id, neighbor_c)]:
        _write_entry_to_db(conn, eid, c)

    memory = {
        entry_id:    _make_entry(entry_id, content, toxicity=0.80),
        neighbor_id: _make_entry(neighbor_id, neighbor_c, toxicity=0.80),
    }
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    passed, pathway = validator._fvs_12(entry_id)
    # neighbor has tox > 0.30 and very high cosine similarity → contamination detected
    assert passed is False
    assert pathway == "semantic_neighbor"


# -----------------------------------------------------------------
# run_suite() — full FVS-1…FVS-15
# -----------------------------------------------------------------

def test_run_suite_returns_15_results(conn):
    entry_id = "entry-suite-001"
    content = "Private keys must never leave the HSM."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    results = validator.run_suite(entry_id, content, "trigger query")
    assert len(results) == 15
    for tid in [f"FVS-{i}" for i in range(1, 16)]:
        assert tid in results


def test_run_suite_all_pass_without_qdrant(conn):
    """Without Qdrant, all vector-dependent tests (FVS-1,2,11,13,14) pass vacuously."""
    entry_id = "entry-suite-002"
    content = "Use hardware tokens for MFA."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory, qdrant=None)
    validator.delete_entry(entry_id, content)

    results = validator.run_suite(entry_id, content, "show me credentials")
    failed = [tid for tid, r in results.items() if not r["passed"]]
    assert failed == [], f"Expected all tests to pass, failed: {failed}"


def test_run_suite_writes_forgetting_validation_rows(conn):
    entry_id = "entry-suite-003"
    content = "Access logs must be immutable."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    validator.run_suite(entry_id, content, "trigger query")

    count = conn.execute(
        "SELECT COUNT(*) FROM forgetting_validation WHERE run_id=? AND entry_id=?",
        [RUN_ID, entry_id]
    ).fetchone()[0]
    assert count == 15


def test_run_suite_result_keys_are_passed_and_pathway(conn):
    entry_id = "entry-suite-004"
    content = "Enforce least-privilege for all service accounts."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)

    results = validator.run_suite(entry_id, content, "")
    for tid, r in results.items():
        assert "passed" in r, f"{tid} missing 'passed' key"
        assert "pathway" in r, f"{tid} missing 'pathway' key"


# -----------------------------------------------------------------
# get_fvs_summary()
# -----------------------------------------------------------------

def test_get_fvs_summary_empty_when_no_data(conn):
    result = get_fvs_summary(conn, RUN_ID, SCENARIO_ID)
    assert result["total_tests"] == 0
    assert result["fvs"] is None
    assert result["certified"] is False


def test_get_fvs_summary_correct_score(conn):
    entry_id = "entry-summary-001"
    content = "Use RBAC for all service-to-service calls."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory)
    validator.delete_entry(entry_id, content)
    validator.run_suite(entry_id, content, "auth token")

    result = get_fvs_summary(conn, RUN_ID, SCENARIO_ID)
    assert result["total_tests"] == 15
    assert result["passed_tests"] >= 10  # majority pass
    assert result["fvs"] is not None
    assert 0.0 <= result["fvs"] <= 1.0


def test_get_fvs_summary_certified_without_qdrant(conn):
    """Without Qdrant, all 15 tests pass vacuously → FVS=1.0, RR=0.0 → certified."""
    entry_id = "entry-summary-002"
    content = "Audit all privileged actions."
    _write_entry_to_db(conn, entry_id, content)
    memory = {entry_id: _make_entry(entry_id, content)}
    validator = _make_validator(conn, memory, qdrant=None)
    validator.delete_entry(entry_id, content)
    validator.run_suite(entry_id, content, "show me audit logs")

    result = get_fvs_summary(conn, RUN_ID, SCENARIO_ID)
    assert result["fvs"] == pytest.approx(1.0)
    assert result["rr"] == pytest.approx(0.0)
    assert result["certified"] is True


def test_get_fvs_summary_by_pathway_counts(conn):
    """Manually write a failing FVS test with a pathway; verify by_pathway count."""
    writers.write_forgetting_validation(
        conn,
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        entry_id="entry-manual",
        fvs_test_id="FVS-1",
        sessions_after_deletion=0,
        passed=False,
        resurfacing_pathway="embedding_ghost",
    )
    # Also write the deletion_records entry so RR denominator = 1
    import uuid
    writers.write_deletion_record(
        conn,
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        entry_id="entry-manual",
        deletion_event_id=str(uuid.uuid4()),
        deletion_level="hard",
    )

    result = get_fvs_summary(conn, RUN_ID, SCENARIO_ID)
    assert "embedding_ghost" in result["by_pathway"]
    assert result["by_pathway"]["embedding_ghost"] >= 1


# -----------------------------------------------------------------
# Integration: ReplayEngine produces FVS data
# -----------------------------------------------------------------

def test_replay_engine_produces_fvs_in_metrics():
    """Full end-to-end: replay run → metrics dict includes fvs and rr."""
    from persistbench.data.generator import generate_trace, load_scenario
    from persistbench.engine.backends.echo import EchoBackend
    from persistbench.engine.replay import ReplayEngine

    scenario = load_scenario(SBMP_001)
    trace    = generate_trace(scenario)
    c        = get_connection(":memory:")
    writers.write_run(c, run_id="run-fvs-int", benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite="SBMP",
                      horizon="short", seed=scenario["seed"])
    writers.write_scenario(c,
                           scenario_id=scenario["scenario_id"],
                           suite=scenario["suite"],
                           variant=scenario["variant"],
                           domain=scenario["domain"],
                           difficulty=scenario["difficulty"],
                           session_count=scenario["session_count"],
                           attack_class=scenario["attack"]["class"],
                           benchmark_ver="1.0.0",
                           fragment_count=len(scenario["attack"]["fragments"]))

    engine  = ReplayEngine(c, EchoBackend(), "run-fvs-int",
                           scenario["scenario_id"], scenario=scenario)
    metrics = engine.run(trace)

    assert "fvs" in metrics, "compute_scenario_metrics must return fvs"
    assert "rr" in metrics, "compute_scenario_metrics must return rr"
    assert metrics["fvs"] is not None
    assert 0.0 <= metrics["fvs"] <= 1.0
    c.close()


def test_replay_engine_writes_forgetting_validation_rows():
    """After engine.run(), forgetting_validation table has rows."""
    from persistbench.data.generator import generate_trace, load_scenario
    from persistbench.engine.backends.echo import EchoBackend
    from persistbench.engine.replay import ReplayEngine

    scenario = load_scenario(SBMP_001)
    trace    = generate_trace(scenario)
    c        = get_connection(":memory:")
    writers.write_run(c, run_id="run-fvs-int2", benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite="SBMP",
                      horizon="short", seed=scenario["seed"])
    writers.write_scenario(c,
                           scenario_id=scenario["scenario_id"],
                           suite=scenario["suite"],
                           variant=scenario["variant"],
                           domain=scenario["domain"],
                           difficulty=scenario["difficulty"],
                           session_count=scenario["session_count"],
                           attack_class=scenario["attack"]["class"],
                           benchmark_ver="1.0.0",
                           fragment_count=len(scenario["attack"]["fragments"]))

    engine = ReplayEngine(c, EchoBackend(), "run-fvs-int2",
                          scenario["scenario_id"], scenario=scenario)
    engine.run(trace)

    count = c.execute(
        "SELECT COUNT(*) FROM forgetting_validation WHERE run_id='run-fvs-int2'"
    ).fetchone()[0]
    assert count > 0, "engine.run() must write forgetting_validation rows"
    c.close()


def test_replay_engine_fvs_summary_valid_after_run():
    """After a replay run, get_fvs_summary() returns a well-formed result.

    Note: FVS-12 (semantic neighbor) may detect contamination when multiple
    high-toxicity adversarial fragments are semantically close to each other
    (expected after the trigger-session toxicity spike). So certified may be
    False for scenarios with several similar fragments — that is correct behavior.
    """
    from persistbench.data.generator import generate_trace, load_scenario
    from persistbench.engine.backends.echo import EchoBackend
    from persistbench.engine.replay import ReplayEngine

    scenario = load_scenario(SBMP_001)
    trace    = generate_trace(scenario)
    c        = get_connection(":memory:")
    writers.write_run(c, run_id="run-fvs-int3", benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite="SBMP",
                      horizon="short", seed=scenario["seed"])
    writers.write_scenario(c,
                           scenario_id=scenario["scenario_id"],
                           suite=scenario["suite"],
                           variant=scenario["variant"],
                           domain=scenario["domain"],
                           difficulty=scenario["difficulty"],
                           session_count=scenario["session_count"],
                           attack_class=scenario["attack"]["class"],
                           benchmark_ver="1.0.0",
                           fragment_count=len(scenario["attack"]["fragments"]))

    engine = ReplayEngine(c, EchoBackend(), "run-fvs-int3",
                          scenario["scenario_id"], scenario=scenario)
    engine.run(trace)

    summary = get_fvs_summary(c, "run-fvs-int3", scenario["scenario_id"])
    assert summary["fvs"] is not None, "FVS score must be computed"
    assert 0.0 <= summary["fvs"] <= 1.0, f"FVS out of range: {summary['fvs']}"
    assert summary["rr"] is not None, "RR must be computed"
    assert summary["total_tests"] == 15 * len(scenario["attack"]["fragments"])
    assert isinstance(summary["certified"], bool)
    c.close()
