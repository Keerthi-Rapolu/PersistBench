import pytest

from persistbench.db.init import get_connection
from persistbench.db import writers, queries


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    yield c
    c.close()


def seed_minimal_run(conn):
    writers.write_run(conn, run_id="run-001", benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="gpt-4o", suite="SBMP",
                      horizon="short", seed=42)
    writers.write_scenario(conn, scenario_id="sbmp-001", suite="SBMP",
                           variant="direct_accumulation",
                           domain="software_development",
                           difficulty="medium", session_count=4,
                           attack_class="SBMP", benchmark_ver="1.0.0",
                           fragment_count=3)

    for sid in range(1, 5):
        writers.write_session(conn, run_id="run-001", scenario_id="sbmp-001",
                              session_id=sid,
                              is_attack_session=(sid == 2),
                              is_trigger_session=(sid == 4),
                              is_probe_session=(sid in (2, 4)),
                              bdi_value=sid * 0.01,
                              safety_score=0.95 - sid * 0.01,
                              memory_risk_score=0.10 + sid * 0.02)

    for tid in range(1, 5):
        writers.write_turn(conn, run_id="run-001", scenario_id="sbmp-001",
                           session_id=1, turn_id=tid, role="user",
                           content_hash=f"sha256:turn{tid}",
                           is_benign=(tid != 3),
                           is_trigger=(tid == 4),
                           fragment_id="f1" if tid == 3 else None)

    writers.write_memory_entry(conn, run_id="run-001", scenario_id="sbmp-001",
                               entry_id="mem-001", created_session=1,
                               created_turn=3, content_hash="sha256:aaa",
                               lifecycle_stage="reinforced",
                               confidence=0.77, trust_score=0.83,
                               toxicity_score=0.05,
                               is_adversarial=True,
                               adversarial_fragment_id="f1")

    writers.write_provenance_event(conn, event_id="evt-001",
                                   run_id="run-001", scenario_id="sbmp-001",
                                   session_id=1, agent_id="agent-a",
                                   entry_id="mem-001", event_type="create",
                                   confidence_after=0.72, trust_after=0.80,
                                   toxicity_after=0.05)
    writers.write_provenance_event(conn, event_id="evt-002",
                                   run_id="run-001", scenario_id="sbmp-001",
                                   session_id=3, agent_id="agent-a",
                                   entry_id="mem-001", event_type="reinforce",
                                   confidence_before=0.72, confidence_after=0.77,
                                   trust_before=0.80, trust_after=0.83,
                                   toxicity_before=0.05, toxicity_after=0.05)

    writers.write_defense_flag(conn, flag_id="flag-001", run_id="run-001",
                               scenario_id="sbmp-001", session_id=3,
                               threat_class="SBMP", confidence=0.88,
                               action="quarantine", is_true_positive=True)

    writers.write_scenario_metrics(conn, run_id="run-001",
                                   scenario_id="sbmp-001",
                                   aps=0.41, rls=0.35, ups=0.88,
                                   attack_detected=True, detection_session=3,
                                   flags_emitted=1, false_positives=0,
                                   composite_score=0.535)
    writers.write_suite_metrics(conn, run_id="run-001", suite="ALL",
                                aps_mean=0.41, aps_std=0.08,
                                rls_mean=0.35, rls_std=0.07,
                                ups=0.88, composite_score=0.535,
                                scenario_count=1)


# -----------------------------------------------------------------
# Schema
# -----------------------------------------------------------------

def test_schema_core_tables(conn):
    tables = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    core = {"runs", "scenarios", "sessions", "turns",
            "memory_entries", "provenance_events",
            "scenario_metrics", "defense_flags"}
    assert core.issubset(tables), f"Missing: {core - tables}"


def test_schema_optional_tables(conn):
    tables = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    optional = {"run_scenarios", "memory_entry_snapshots", "memory_conflicts",
                "provenance_lineage", "deletion_records", "suite_metrics",
                "governance_actions", "behavioral_probes", "forgetting_validation"}
    assert optional.issubset(tables), f"Missing: {optional - tables}"


# -----------------------------------------------------------------
# Writers
# -----------------------------------------------------------------

def test_write_run(conn):
    writers.write_run(conn, run_id="r1", benchmark_ver="1.0.0",
                      defense_name="X", defense_ver="1.0",
                      model_id="gpt-4o", suite="SBMP",
                      horizon="short", seed=1)
    row = conn.execute("SELECT status FROM runs WHERE run_id='r1'").fetchone()
    assert row[0] == "running"


def test_write_scenario_idempotent(conn):
    for _ in range(3):
        writers.write_scenario(conn, scenario_id="s1", suite="SBMP",
                               variant="v", domain="d", difficulty="easy",
                               session_count=5, attack_class="SBMP",
                               benchmark_ver="1.0.0")
    count = conn.execute("SELECT count(*) FROM scenarios WHERE scenario_id='s1'").fetchone()[0]
    assert count == 1


def test_write_provenance_chain(conn):
    writers.write_run(conn, run_id="r2", benchmark_ver="1.0.0",
                      defense_name="X", defense_ver="1.0",
                      model_id="gpt-4o", suite="SBMP",
                      horizon="short", seed=99)
    for i in range(1, 6):
        writers.write_provenance_event(
            conn, event_id=f"e{i}", run_id="r2", scenario_id="sc1",
            session_id=i, agent_id="a", entry_id="m1",
            event_type="create" if i == 1 else "reinforce",
            confidence_after=0.7 + i * 0.01, trust_after=0.8)

    hashes = [r[0] for r in conn.execute(
        "SELECT chain_hash FROM provenance_events WHERE run_id='r2' ORDER BY created_at"
    ).fetchall()]
    assert len(hashes) == 5
    assert len(set(hashes)) == 5, "All chain hashes must be unique"


def test_write_memory_entry_replace(conn):
    writers.write_run(conn, run_id="r3", benchmark_ver="1.0.0",
                      defense_name="X", defense_ver="1.0",
                      model_id="gpt-4o", suite="SBMP",
                      horizon="short", seed=7)
    kwargs = dict(run_id="r3", scenario_id="sc1", entry_id="m1",
                  created_session=1, created_turn=1,
                  content_hash="sha256:x", lifecycle_stage="created",
                  confidence=0.5, trust_score=0.6)
    writers.write_memory_entry(conn, **kwargs)
    updated = {**kwargs, "lifecycle_stage": "reinforced",
               "confidence": 0.75, "trust_score": 0.82}
    writers.write_memory_entry(conn, **updated)
    row = conn.execute(
        "SELECT lifecycle_stage, trust_score FROM memory_entries WHERE entry_id='m1'"
    ).fetchone()
    assert row[0] == "reinforced"
    assert row[1] == pytest.approx(0.82)


# -----------------------------------------------------------------
# Queries
# -----------------------------------------------------------------

def test_bdi_time_series(conn):
    seed_minimal_run(conn)
    series = queries.get_bdi_time_series(conn, "run-001", "sbmp-001")
    assert len(series) == 4
    assert series[0]["bdi"] == pytest.approx(0.01)
    assert series[3]["bdi"] == pytest.approx(0.04)
    assert series[0]["safety_score"] == pytest.approx(0.94)
    assert all(k in series[0] for k in ("session", "bdi", "safety_score", "mrs"))


def test_bdi_time_series_empty(conn):
    assert queries.get_bdi_time_series(conn, "no-run", "no-scenario") == []


def test_scenario_metrics(conn):
    seed_minimal_run(conn)
    m = queries.get_scenario_metrics(conn, "run-001", "sbmp-001")
    assert m is not None
    assert m["aps"] == pytest.approx(0.41)
    assert m["rls"] == pytest.approx(0.35)
    assert m["composite"] == pytest.approx(0.535)
    assert m["attack_detected"] is True
    assert m["detection_session"] == 3


def test_scenario_metrics_missing(conn):
    assert queries.get_scenario_metrics(conn, "ghost", "ghost") is None


def test_provenance_events(conn):
    seed_minimal_run(conn)
    events = queries.get_provenance_events(conn, "run-001", "sbmp-001", "mem-001")
    assert len(events) == 2
    assert events[0]["event_type"] == "create"
    assert events[1]["event_type"] == "reinforce"
    # chain must advance
    assert events[0]["chain_hash"] != events[1]["chain_hash"]
    assert all(e["chain_hash"].startswith("sha256:") for e in events)


def test_provenance_events_empty(conn):
    assert queries.get_provenance_events(conn, "x", "y", "z") == []


def test_defense_summary(conn):
    seed_minimal_run(conn)
    s = queries.get_defense_summary(conn, "run-001", "sbmp-001")
    assert s["total"] == 1
    assert s["true_positives"] == 1
    assert s["false_positives"] == 0
    assert s["tpr"] == pytest.approx(1.0)


def test_defense_summary_no_flags(conn):
    writers.write_run(conn, run_id="empty", benchmark_ver="1.0.0",
                      defense_name="X", defense_ver="1.0",
                      model_id="gpt-4o", suite="SBMP",
                      horizon="short", seed=0)
    s = queries.get_defense_summary(conn, "empty", "sc1")
    assert s["total"] == 0
    assert s["tpr"] is None


def test_leaderboard_requires_complete(conn):
    seed_minimal_run(conn)
    assert queries.get_leaderboard(conn) == []
    conn.execute("UPDATE runs SET status='complete' WHERE run_id='run-001'")
    board = queries.get_leaderboard(conn)
    assert len(board) == 1
    assert board[0]["defense"] == "NoDefense"
    assert board[0]["composite"] == pytest.approx(0.535)
    assert board[0]["run_count"] == 1


def test_leaderboard_ordering(conn):
    for i, (name, score) in enumerate([("DefA", 0.80), ("DefB", 0.60), ("DefC", 0.95)]):
        rid = f"run-{i}"
        writers.write_run(conn, run_id=rid, benchmark_ver="1.0.0",
                          defense_name=name, defense_ver="1.0",
                          model_id="gpt-4o", suite="SBMP",
                          horizon="short", seed=i)
        conn.execute(f"UPDATE runs SET status='complete' WHERE run_id='{rid}'")
        writers.write_suite_metrics(conn, run_id=rid, suite="ALL",
                                    aps_mean=score, aps_std=0.0,
                                    rls_mean=score, rls_std=0.0,
                                    ups=score, composite_score=score,
                                    scenario_count=1)
    board = queries.get_leaderboard(conn)
    scores = [r["composite"] for r in board]
    assert scores == sorted(scores, reverse=True)
    assert board[0]["defense"] == "DefC"


# -----------------------------------------------------------------
# V2 stubs raise correctly
# -----------------------------------------------------------------

def test_v2_writer_stubs_raise():
    for fn in (writers.write_run_scenario, writers.write_memory_entry_snapshot,
               writers.write_provenance_lineage, writers.write_deletion_record,
               writers.write_memory_conflict, writers.write_governance_action,
               writers.write_behavioral_probe, writers.write_forgetting_validation):
        with pytest.raises(NotImplementedError):
            fn()


def test_v2_query_stubs_raise():
    for fn in (queries.get_trust_evolution, queries.get_cra,
               queries.get_provenance_chain, queries.get_fvs_summary):
        with pytest.raises(NotImplementedError):
            fn()


# -----------------------------------------------------------------
# Full end-to-end
# -----------------------------------------------------------------

def test_full_integration(conn):
    seed_minimal_run(conn)

    # All 4 sessions recorded
    series = queries.get_bdi_time_series(conn, "run-001", "sbmp-001")
    assert len(series) == 4

    # BDI increases each session (seeded 0.01 * sid)
    bdis = [r["bdi"] for r in series]
    assert bdis == sorted(bdis)

    # Provenance chain is intact
    events = queries.get_provenance_events(conn, "run-001", "sbmp-001", "mem-001")
    assert len(events) == 2
    assert events[0]["chain_hash"] != events[1]["chain_hash"]

    # Defense: 1 flag, 1 TP
    summary = queries.get_defense_summary(conn, "run-001", "sbmp-001")
    assert summary["tpr"] == pytest.approx(1.0)

    # Metrics stored correctly
    m = queries.get_scenario_metrics(conn, "run-001", "sbmp-001")
    assert m["composite"] == pytest.approx(0.535)

    # Leaderboard empty until complete
    assert queries.get_leaderboard(conn) == []
    conn.execute("UPDATE runs SET status='complete' WHERE run_id='run-001'")
    board = queries.get_leaderboard(conn)
    assert board[0]["composite"] == pytest.approx(0.535)

    # Turn-level data present
    turns = conn.execute(
        "SELECT count(*) FROM turns WHERE run_id='run-001'"
    ).fetchone()[0]
    assert turns == 4

    # Adversarial memory entry flagged
    row = conn.execute(
        "SELECT is_adversarial, adversarial_fragment_id FROM memory_entries WHERE entry_id='mem-001'"
    ).fetchone()
    assert row[0] is True
    assert row[1] == "f1"
