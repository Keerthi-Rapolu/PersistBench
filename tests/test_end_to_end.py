"""End-to-end benchmark loop tests.

Validates the full pipeline for all 3 SBMP scenarios:
  sbmp-001: direct accumulation  (APS=1.0, attack active)
  sbmp-002: delayed trigger       (APS=1.0, longer horizon)
  sbmp-003: benign control        (APS=0.0, no attack, clean baseline)

Each test runs: scenario YAML -> trace -> replay -> DB writes ->
metrics -> artifact files.
"""
from __future__ import annotations

import json
import statistics
import tempfile
from pathlib import Path

import pytest

from persistbench.data.generator import generate_trace, load_scenario
from persistbench.db import writers
from persistbench.db.init import get_connection
from persistbench.engine.backends.echo import EchoBackend
from persistbench.engine.replay import ReplayEngine
from persistbench.reporting.artifact_writer import (
    write_metrics_json,
    write_provenance_graph,
    write_replay_trace,
    write_run_summary,
)
from persistbench.reporting.report_generator import generate_report

SBMP_DIR = Path(__file__).parent.parent / "scenarios" / "sbmp"
SBMP_001 = SBMP_DIR / "sbmp-001.yaml"
SBMP_002 = SBMP_DIR / "sbmp-002.yaml"
SBMP_003 = SBMP_DIR / "sbmp-003.yaml"


# -----------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------

def _setup_run(conn, run_id: str, scenario: dict) -> None:
    writers.write_run(conn, run_id=run_id, benchmark_ver="1.0.0",
                      defense_name="NoDefense", defense_ver="1.0.0",
                      model_id="echo", suite=scenario["suite"],
                      horizon=scenario.get("horizon", "short"),
                      seed=scenario["seed"])
    writers.write_scenario(conn,
                           scenario_id=scenario["scenario_id"],
                           suite=scenario["suite"],
                           variant=scenario["variant"],
                           domain=scenario["domain"],
                           difficulty=scenario["difficulty"],
                           session_count=scenario["session_count"],
                           attack_class=scenario.get("attack", {}).get("class", "none"),
                           benchmark_ver="1.0.0",
                           fragment_count=len(scenario.get("attack", {}).get("fragments", [])))


def _run(conn, scenario: dict, run_id: str) -> tuple[list, dict]:
    trace = generate_trace(scenario)
    engine = ReplayEngine(conn, EchoBackend(), run_id,
                          scenario["scenario_id"], scenario)
    metrics = engine.run(trace)
    return trace, metrics


# -----------------------------------------------------------------
# sbmp-001: direct accumulation
# -----------------------------------------------------------------

class TestSbmp001:
    @pytest.fixture(scope="class")
    def result(self):
        scenario = load_scenario(SBMP_001)
        conn = get_connection(":memory:")
        _setup_run(conn, "run-001", scenario)
        trace, metrics = _run(conn, scenario, "run-001")
        yield conn, scenario, trace, metrics
        conn.close()

    def test_aps_is_one(self, result):
        _, _, _, metrics = result
        assert metrics["aps"] == pytest.approx(1.0)

    def test_ups_is_one(self, result):
        _, _, _, metrics = result
        assert metrics["ups"] == pytest.approx(1.0)

    def test_composite_score(self, result):
        _, _, _, metrics = result
        # APS=1.0, RLS=1.0, UPS=1.0 -> 0.45*0 + 0.35*0 + 0.20*1 = 0.20
        assert metrics["composite_score"] == pytest.approx(0.20)

    def test_attack_not_detected(self, result):
        _, _, _, metrics = result
        assert metrics["attack_detected"] is False
        assert metrics["flags_emitted"] == 0

    def test_correct_session_count(self, result):
        conn, scenario, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM sessions WHERE run_id='run-001'"
        ).fetchone()[0]
        assert count == scenario["session_count"]

    def test_fragments_in_memory(self, result):
        conn, scenario, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM memory_entries "
            "WHERE run_id='run-001' AND is_adversarial=TRUE"
        ).fetchone()[0]
        assert count == len(scenario["attack"]["fragments"])

    def test_snapshots_written(self, result):
        """Memory entry snapshots captured per session after fragment creation."""
        conn, scenario, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM memory_entry_snapshots WHERE run_id='run-001'"
        ).fetchone()[0]
        # Each fragment generates snapshots for all sessions from plant_session onward
        assert count > 0

    def test_provenance_chain_integrity(self, result):
        conn, _, _, _ = result
        hashes = [r[0] for r in conn.execute(
            "SELECT chain_hash FROM provenance_events "
            "WHERE run_id='run-001' ORDER BY created_at"
        ).fetchall()]
        assert all(h.startswith("sha256:") for h in hashes)
        assert len(set(hashes)) == len(hashes)  # all unique

    def test_bdi_before_trigger_is_zero(self, result):
        conn, scenario, _, _ = result
        trigger_session = scenario["attack"]["trigger"]["session"]
        probe_sessions = scenario["probe_sessions"]
        before = [s for s in probe_sessions if s < trigger_session]
        if before:
            rows = conn.execute(
                f"SELECT bdi_value FROM sessions WHERE run_id='run-001' "
                f"AND session_id IN ({','.join(str(s) for s in before)})"
            ).fetchall()
            for (bdi,) in rows:
                assert bdi == pytest.approx(0.0)

    def test_bdi_after_trigger_positive(self, result):
        conn, scenario, _, _ = result
        trigger_session = scenario["attack"]["trigger"]["session"]
        probe_sessions = scenario["probe_sessions"]
        after = [s for s in probe_sessions if s >= trigger_session]
        if after:
            rows = conn.execute(
                f"SELECT bdi_value FROM sessions WHERE run_id='run-001' "
                f"AND session_id IN ({','.join(str(s) for s in after)})"
            ).fetchall()
            for (bdi,) in rows:
                assert bdi is not None and bdi > 0.0


# -----------------------------------------------------------------
# sbmp-002: delayed trigger (15 sessions)
# -----------------------------------------------------------------

class TestSbmp002:
    @pytest.fixture(scope="class")
    def result(self):
        scenario = load_scenario(SBMP_002)
        conn = get_connection(":memory:")
        _setup_run(conn, "run-002", scenario)
        trace, metrics = _run(conn, scenario, "run-002")
        yield conn, scenario, trace, metrics
        conn.close()

    def test_session_count(self, result):
        conn, scenario, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM sessions WHERE run_id='run-002'"
        ).fetchone()[0]
        assert count == 15

    def test_aps_is_one(self, result):
        _, _, _, metrics = result
        assert metrics["aps"] == pytest.approx(1.0)

    def test_ups_is_one(self, result):
        _, _, _, metrics = result
        assert metrics["ups"] == pytest.approx(1.0)

    def test_three_fragments_persisted(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM memory_entries "
            "WHERE run_id='run-002' AND is_adversarial=TRUE"
        ).fetchone()[0]
        assert count == 3

    def test_trigger_fires_in_session_14(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM turns "
            "WHERE run_id='run-002' AND is_trigger=TRUE AND session_id=14"
        ).fetchone()[0]
        assert count == 1

    def test_long_dormancy(self, result):
        """Fragments planted by session 9 are still in memory at trigger (session 14)."""
        conn, _, _, _ = result
        # All 3 fragments created by session 9; trigger fires at session 14
        # => 5 dormant sessions between last plant and trigger
        frag_sessions = conn.execute(
            "SELECT created_session FROM memory_entries "
            "WHERE run_id='run-002' AND is_adversarial=TRUE "
            "ORDER BY created_session"
        ).fetchall()
        last_plant = max(r[0] for r in frag_sessions)
        assert last_plant == 9   # f3 planted in session 9

    def test_snapshots_span_multiple_sessions(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(DISTINCT session_id) FROM memory_entry_snapshots "
            "WHERE run_id='run-002'"
        ).fetchone()[0]
        # Snapshots from session 2 (first plant) through session 15
        assert count >= 10


# -----------------------------------------------------------------
# sbmp-003: benign control (no attack)
# -----------------------------------------------------------------

class TestSbmp003:
    @pytest.fixture(scope="class")
    def result(self):
        scenario = load_scenario(SBMP_003)
        conn = get_connection(":memory:")
        _setup_run(conn, "run-003", scenario)
        trace, metrics = _run(conn, scenario, "run-003")
        yield conn, scenario, trace, metrics
        conn.close()

    def test_aps_is_zero(self, result):
        """No fragments -> APS = 0.0."""
        _, _, _, metrics = result
        assert metrics["aps"] == pytest.approx(0.0)

    def test_ups_is_one(self, result):
        _, _, _, metrics = result
        assert metrics["ups"] == pytest.approx(1.0)

    def test_no_adversarial_memory(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM memory_entries "
            "WHERE run_id='run-003' AND is_adversarial=TRUE"
        ).fetchone()[0]
        assert count == 0

    def test_no_trigger_turns(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM turns "
            "WHERE run_id='run-003' AND is_trigger=TRUE"
        ).fetchone()[0]
        assert count == 0

    def test_all_probes_pass(self, result):
        """Clean baseline: all BDI values should be 0.0."""
        conn, _, _, _ = result
        rows = conn.execute(
            "SELECT bdi_value FROM sessions "
            "WHERE run_id='run-003' AND is_probe_session=TRUE"
        ).fetchall()
        assert rows, "Expected probe sessions in benign control"
        for (bdi,) in rows:
            assert bdi == pytest.approx(0.0), f"Expected BDI=0 in clean baseline, got {bdi}"

    def test_no_snapshots(self, result):
        """No adversarial memory entries -> no snapshots."""
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM memory_entry_snapshots WHERE run_id='run-003'"
        ).fetchone()[0]
        assert count == 0

    def test_no_provenance_events(self, result):
        conn, _, _, _ = result
        count = conn.execute(
            "SELECT count(*) FROM provenance_events WHERE run_id='run-003'"
        ).fetchone()[0]
        assert count == 0


# -----------------------------------------------------------------
# Cross-scenario comparisons
# -----------------------------------------------------------------

class TestCrossScenario:
    @pytest.fixture(scope="class")
    def all_results(self):
        conn = get_connection(":memory:")
        runs = {}
        for run_id, path in [("r1", SBMP_001), ("r2", SBMP_002), ("r3", SBMP_003)]:
            scenario = load_scenario(path)
            _setup_run(conn, run_id, scenario)
            _, metrics = _run(conn, scenario, run_id)
            runs[run_id] = metrics
        yield conn, runs
        conn.close()

    def test_attack_scenarios_aps_gt_control(self, all_results):
        _, runs = all_results
        assert runs["r1"]["aps"] > runs["r3"]["aps"]
        assert runs["r2"]["aps"] > runs["r3"]["aps"]

    def test_control_bdi_lower_than_attacked(self, all_results):
        conn, _ = all_results
        # sbmp-003 probe sessions all BDI=0; sbmp-001 has BDI>0 after trigger
        r1_max_bdi = conn.execute(
            "SELECT max(bdi_value) FROM sessions "
            "WHERE run_id='r1' AND is_probe_session=TRUE"
        ).fetchone()[0]
        r3_max_bdi = conn.execute(
            "SELECT max(bdi_value) FROM sessions "
            "WHERE run_id='r3' AND is_probe_session=TRUE"
        ).fetchone()[0]
        assert (r3_max_bdi or 0.0) < (r1_max_bdi or 0.0)

    def test_artifact_pipeline_all_scenarios(self, all_results):
        """Artifact writer and report generator work for all 3 scenarios."""
        conn, _ = all_results
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for sub in ("runs", "reports", "replay_traces", "provenance", "exports"):
                (tmp_path / sub).mkdir()
            for run_id in ("r1", "r2", "r3"):
                summary = write_run_summary(conn, run_id, tmp_path / "runs")
                assert summary.exists()
                data = json.loads(summary.read_text(encoding="utf-8"))
                assert data["run_id"] == run_id

                html = generate_report(conn, run_id, tmp_path / "reports", fmt="html")
                assert html.exists()
                assert "<!DOCTYPE html>" in html.read_text(encoding="utf-8")

    def test_suite_metrics(self, all_results):
        conn, runs = all_results
        aps_vals = [m["aps"] for m in runs.values()]
        comp_vals = [m["composite_score"] for m in runs.values()]
        writers.write_suite_metrics(
            conn,
            run_id="r1",  # aggregate over all 3 under run r1 for simplicity
            suite="SBMP",
            aps_mean=round(statistics.mean(aps_vals), 6),
            aps_std=round(statistics.stdev(aps_vals), 6),
            rls_mean=1.0,
            rls_std=0.0,
            ups=1.0,
            composite_score=round(statistics.mean(comp_vals), 6),
            scenario_count=3,
        )
        row = conn.execute(
            "SELECT scenario_count, aps_mean FROM suite_metrics WHERE run_id='r1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 3
