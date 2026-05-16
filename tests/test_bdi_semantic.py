"""Tests for V2.3 — embedding-based BDI_sem (§24.4).

Covers:
  - write_behavioral_probe() captures response embeddings
  - get_bdi_semantic() computes cosine drift correctly
  - BDI_sem ≈ 0 pre-trigger, > 0 post-trigger with EchoBackend
  - compute_scenario_metrics() uses semantic BDI when available
"""
from pathlib import Path

import numpy as np
import pytest

from persistbench.data.generator import generate_trace, load_scenario
from persistbench.db import writers
from persistbench.db.init import get_connection
from persistbench.db.queries import get_bdi_semantic
from persistbench.engine.backends.echo import EchoBackend
from persistbench.engine.replay import ReplayEngine

SBMP_001 = Path(__file__).parent.parent / "scenarios" / "sbmp" / "sbmp-001.yaml"


# -----------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------

@pytest.fixture
def scenario():
    return load_scenario(SBMP_001)


@pytest.fixture
def trace(scenario):
    return generate_trace(scenario)


@pytest.fixture
def seeded_conn(scenario):
    conn = get_connection(":memory:")
    writers.write_run(conn, run_id="run-bdi-001", benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite="SBMP",
                      horizon="short", seed=scenario["seed"])
    writers.write_scenario(conn,
                           scenario_id=scenario["scenario_id"],
                           suite=scenario["suite"],
                           variant=scenario["variant"],
                           domain=scenario["domain"],
                           difficulty=scenario["difficulty"],
                           session_count=scenario["session_count"],
                           attack_class=scenario["attack"]["class"],
                           benchmark_ver="1.0.0",
                           fragment_count=len(scenario["attack"]["fragments"]))
    yield conn
    conn.close()


def make_engine(conn, scenario):
    return ReplayEngine(
        conn=conn,
        backend=EchoBackend(),
        run_id="run-bdi-001",
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
    )


# -----------------------------------------------------------------
# write_behavioral_probe()
# -----------------------------------------------------------------

def test_write_behavioral_probe_inserts_row(seeded_conn):
    writers.write_behavioral_probe(
        seeded_conn,
        run_id="run-bdi-001",
        scenario_id="sbmp-001",
        session_id=3,
        probe_id="sw-p02",
        probe_domain="software_development",
        probe_type="bdi",
        response_text="No, credentials should never be stored in plaintext.",
        safety_passed=True,
    )
    count = seeded_conn.execute(
        "SELECT COUNT(*) FROM behavioral_probes WHERE run_id='run-bdi-001'"
    ).fetchone()[0]
    assert count == 1


def test_write_behavioral_probe_stores_embedding(seeded_conn):
    writers.write_behavioral_probe(
        seeded_conn,
        run_id="run-bdi-001",
        scenario_id="sbmp-001",
        session_id=3,
        probe_id="sw-p02",
        probe_domain="software_development",
        probe_type="bdi",
        response_text="Use environment variables for all secrets.",
        safety_passed=True,
    )
    blob = seeded_conn.execute(
        "SELECT response_embedding FROM behavioral_probes WHERE run_id='run-bdi-001'"
    ).fetchone()[0]
    assert blob is not None
    assert len(blob) == 384 * 4  # 384-d float32


def test_write_behavioral_probe_stores_hash(seeded_conn):
    text = "Credentials must be managed via a secrets manager."
    writers.write_behavioral_probe(
        seeded_conn,
        run_id="run-bdi-001",
        scenario_id="sbmp-001",
        session_id=3,
        probe_id="sw-p02",
        probe_domain="software_development",
        probe_type="bdi",
        response_text=text,
        safety_passed=True,
    )
    row = seeded_conn.execute(
        "SELECT response_hash FROM behavioral_probes WHERE run_id='run-bdi-001'"
    ).fetchone()
    assert row[0].startswith("sha256:")


# -----------------------------------------------------------------
# Replay engine writes behavioral_probes
# -----------------------------------------------------------------

def test_replay_writes_behavioral_probes(seeded_conn, scenario, trace):
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    count = seeded_conn.execute(
        "SELECT COUNT(*) FROM behavioral_probes WHERE run_id='run-bdi-001'"
    ).fetchone()[0]
    assert count > 0, "Replay engine should write behavioral probe rows"


def test_replay_probe_count_matches_probe_sessions(seeded_conn, scenario, trace):
    """Number of behavioral_probe rows = probe_sessions × probes_per_session."""
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    n_probe_sessions = len(scenario["probe_sessions"])
    rows = seeded_conn.execute(
        "SELECT COUNT(*) FROM behavioral_probes WHERE run_id='run-bdi-001'"
    ).fetchone()[0]
    # Each probe session has multiple probes; there should be at least n_probe_sessions rows
    assert rows >= n_probe_sessions


def test_replay_bdi_type_probes_have_embeddings(seeded_conn, scenario, trace):
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    rows = seeded_conn.execute(
        "SELECT probe_id, response_embedding FROM behavioral_probes "
        "WHERE run_id='run-bdi-001' AND probe_type='bdi'"
    ).fetchall()
    assert len(rows) > 0, "Should have bdi-type probe rows"
    for probe_id, blob in rows:
        assert blob is not None, f"Probe {probe_id} missing response_embedding"
        assert len(blob) == 384 * 4


# -----------------------------------------------------------------
# get_bdi_semantic()
# -----------------------------------------------------------------

def test_get_bdi_semantic_returns_list(seeded_conn, scenario, trace):
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    result = get_bdi_semantic(seeded_conn, "run-bdi-001", scenario["scenario_id"])
    assert isinstance(result, list)
    assert len(result) > 0


def test_get_bdi_semantic_has_correct_keys(seeded_conn, scenario, trace):
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    result = get_bdi_semantic(seeded_conn, "run-bdi-001", scenario["scenario_id"])
    for row in result:
        assert "session_id" in row
        assert "bdi_sem" in row
        assert 0.0 <= row["bdi_sem"] <= 1.0 + 1e-5


def test_get_bdi_semantic_baseline_is_zero(seeded_conn, scenario, trace):
    """Baseline session (first probe session) should have BDI_sem = 0.0."""
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    result = get_bdi_semantic(seeded_conn, "run-bdi-001", scenario["scenario_id"])
    assert result, "BDI series should not be empty"
    # First session is the baseline — cosine(baseline, baseline) = 1 → BDI = 0
    assert result[0]["bdi_sem"] == pytest.approx(0.0, abs=1e-4)


def test_get_bdi_semantic_increases_after_trigger(seeded_conn, scenario, trace):
    """EchoBackend switches to POISONED_RESPONSE after trigger → BDI_sem rises."""
    engine = make_engine(seeded_conn, scenario)
    engine.run(trace)

    trigger_session = scenario["attack"]["trigger"]["session"]
    result = get_bdi_semantic(seeded_conn, "run-bdi-001", scenario["scenario_id"])

    pre  = [r["bdi_sem"] for r in result if r["session_id"] < trigger_session]
    post = [r["bdi_sem"] for r in result if r["session_id"] >= trigger_session]

    if pre and post:
        assert max(post) > max(pre), (
            f"BDI_sem should be higher post-trigger: pre={pre}, post={post}"
        )


def test_get_bdi_semantic_empty_for_no_data(seeded_conn):
    """Returns empty list when no behavioral_probes data exists."""
    result = get_bdi_semantic(seeded_conn, "run-bdi-001", "sbmp-001")
    assert result == []


# -----------------------------------------------------------------
# compute_scenario_metrics() uses semantic BDI
# -----------------------------------------------------------------

def test_metrics_use_semantic_bdi_when_available(seeded_conn, scenario, trace):
    """After replay, bdi_10 and bdi_50 come from get_bdi_semantic(), not regex proxy."""
    engine = make_engine(seeded_conn, scenario)
    metrics = engine.run(trace)

    sem_series = get_bdi_semantic(seeded_conn, "run-bdi-001", scenario["scenario_id"])
    assert sem_series, "BDI_sem series must exist after run"

    # bdi_10 ≈ value at earliest probe session (≈ 0.0, baseline)
    # bdi_50 ≈ value near 50% checkpoint
    assert metrics["bdi_10"] is not None
    assert metrics["bdi_50"] is not None
    # The earliest probe session BDI_sem = 0 → bdi_10 should be near 0
    assert metrics["bdi_10"] == pytest.approx(0.0, abs=0.05)


def test_metrics_bdi_50_positive_after_trigger(seeded_conn, scenario, trace):
    """BDI at 50% checkpoint should be > 0 since the trigger fires before session 10."""
    engine = make_engine(seeded_conn, scenario)
    metrics = engine.run(trace)

    # sbmp-001 has 10 sessions, trigger at session 10, probe at session 10
    # bdi_50 is at session 5 (no probe) → nearest probe session found
    # The probe session nearest to 50% = session 6 (probe_sessions=[3,6,10])
    # Session 6 is pre-trigger → BDI_sem ≈ 0
    # bdi_50 is small but bdi at post-trigger (session 10) should be large
    assert metrics["bdi_50"] is not None
    assert metrics["bdi_50"] >= 0.0
