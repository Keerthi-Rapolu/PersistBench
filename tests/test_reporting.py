"""Tests for artifact_writer and report_generator."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from persistbench.data.generator import generate_trace, load_scenario
from persistbench.db.init import get_connection
from persistbench.db import writers
from persistbench.engine.backends.echo import EchoBackend
from persistbench.engine.replay import ReplayEngine
from persistbench.reporting.artifact_writer import (
    write_run_summary,
    write_metrics_json,
    write_replay_trace,
    write_provenance_graph,
    write_governance_events,
)
from persistbench.reporting.report_generator import generate_report

SBMP_001 = Path(__file__).parent.parent / "scenarios" / "sbmp" / "sbmp-001.yaml"


@pytest.fixture(scope="module")
def seeded_run():
    scenario = load_scenario(SBMP_001)
    trace = generate_trace(scenario)
    conn = get_connection(":memory:")
    writers.write_run(conn, run_id="run-001", benchmark_ver="1.0.0",
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
    engine = ReplayEngine(conn, EchoBackend(), "run-001",
                          scenario["scenario_id"], scenario)
    engine.run(trace)
    return conn, scenario, trace


# -----------------------------------------------------------------
# artifact_writer tests
# -----------------------------------------------------------------

def test_write_run_summary(seeded_run):
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = write_run_summary(conn, "run-001", tmp)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-001"
        assert len(data["scenarios"]) == 1
        assert "aps" in data["scenarios"][0]


def test_write_metrics_json(seeded_run):
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = write_metrics_json(conn, "run-001", tmp)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-001"
        assert len(data["metrics"]) == 1
        assert "composite_score" in data["metrics"][0]


def test_write_replay_trace(seeded_run):
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = write_replay_trace(trace, "run-001", tmp)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == len(trace)
        first = json.loads(lines[0])
        assert "session_id" in first and "content_hash" in first


def test_write_provenance_graph(seeded_run):
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = write_provenance_graph(conn, "run-001", tmp)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-001"
        assert len(data["nodes"]) == len(scenario["attack"]["fragments"])
        assert all(e["chain_hash"].startswith("sha256:") for e in data["events"])


def test_write_governance_events(seeded_run):
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = write_governance_events(conn, "run-001", tmp)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-001"
        assert isinstance(data["governance_events"], list)


def test_artifact_json_deterministic(seeded_run):
    """Same run produces identical JSON output on two calls."""
    conn, scenario, trace = seeded_run
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        p1 = write_run_summary(conn, "run-001", tmp1)
        p2 = write_run_summary(conn, "run-001", tmp2)
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")


# -----------------------------------------------------------------
# report_generator tests
# -----------------------------------------------------------------

def test_report_json(seeded_run):
    conn, _, _ = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = generate_report(conn, "run-001", tmp, fmt="json")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run"]["run_id"] == "run-001"
        assert "aps" in data["metrics"]


def test_report_md(seeded_run):
    conn, _, _ = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = generate_report(conn, "run-001", tmp, fmt="md")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        for section in ["Run Metadata", "Core Metrics", "Scenario Breakdown",
                        "Provenance Summary", "Defense Performance"]:
            assert section in content, f"Missing section: {section}"


def test_report_html(seeded_run):
    conn, _, _ = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        path = generate_report(conn, "run-001", tmp, fmt="html")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        for section in ["Run Metadata", "Core Metrics", "Scenario Breakdown",
                        "Provenance Summary", "Defense Performance"]:
            assert section in content, f"Missing section: {section}"


def test_report_invalid_run(seeded_run):
    conn, _, _ = seeded_run
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="not found"):
            generate_report(conn, "nonexistent-run", tmp, fmt="json")
