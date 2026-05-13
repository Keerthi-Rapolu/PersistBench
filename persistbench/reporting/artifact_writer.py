"""Write benchmark artifacts to disk.

All JSON output uses sort_keys=True for deterministic serialization.
Callers are responsible for creating out_dir before calling these functions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from persistbench.data.generator import TurnRecord


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, default=str)


def write_run_summary(conn, run_id: str, out_dir: str | Path) -> Path:
    """Write run metadata + scenario_metrics to artifacts/runs/{run_id}.json."""
    out_dir = Path(out_dir)
    row = conn.execute(
        "SELECT run_id, benchmark_ver, defense_name, defense_ver, model_id, "
        "suite, horizon, seed, created_at "
        "FROM runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"run_id {run_id!r} not found in runs table")

    cols = ["run_id", "benchmark_ver", "defense_name", "defense_ver",
            "model_id", "suite", "horizon", "seed", "created_at"]
    run_data = dict(zip(cols, row))

    scenarios = conn.execute(
        "SELECT scenario_id, aps, rls, ups, composite_score, bdi_10, bdi_50, "
        "attack_detected, flags_emitted, false_positives "
        "FROM scenario_metrics WHERE run_id = ?",
        [run_id],
    ).fetchall()
    scen_cols = ["scenario_id", "aps", "rls", "ups", "composite_score",
                 "bdi_10", "bdi_50", "attack_detected", "flags_emitted", "false_positives"]
    run_data["scenarios"] = [dict(zip(scen_cols, s)) for s in scenarios]

    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(_dump(run_data), encoding="utf-8")
    return out_path


def write_metrics_json(conn, run_id: str, out_dir: str | Path) -> Path:
    """Write flat metrics table for a run to artifacts/runs/{run_id}_metrics.json."""
    out_dir = Path(out_dir)
    rows = conn.execute(
        "SELECT sm.scenario_id, sm.aps, sm.rls, sm.ups, sm.bdi_10, sm.bdi_50, "
        "sm.composite_score, sm.attack_detected, sm.detection_session, "
        "sm.recovery_session, sm.flags_emitted, sm.false_positives, "
        "sm.clean_state_achieved "
        "FROM scenario_metrics sm WHERE sm.run_id = ?",
        [run_id],
    ).fetchall()
    cols = ["scenario_id", "aps", "rls", "ups", "bdi_10", "bdi_50",
            "composite_score", "attack_detected", "detection_session",
            "recovery_session", "flags_emitted", "false_positives",
            "clean_state_achieved"]
    data = {"run_id": run_id, "metrics": [dict(zip(cols, r)) for r in rows]}
    out_path = out_dir / f"{run_id}_metrics.json"
    out_path.write_text(_dump(data), encoding="utf-8")
    return out_path


def write_replay_trace(
    trace: list[TurnRecord], run_id: str, out_dir: str | Path
) -> Path:
    """Write the replay trace as JSONL to artifacts/replay_traces/{run_id}.jsonl."""
    out_dir = Path(out_dir)
    lines = []
    for t in trace:
        lines.append(json.dumps({
            "session_id": t.session_id,
            "turn_id": t.turn_id,
            "role": t.role,
            "content_hash": t.content_hash,
            "is_benign": t.is_benign,
            "is_trigger": t.is_trigger,
            "is_probe": t.is_probe,
            "fragment_id": t.fragment_id,
            "probe_id": t.probe_id,
            "expected_memory_effect": t.expected_memory_effect,
        }, sort_keys=True))
    out_path = out_dir / f"{run_id}.jsonl"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_provenance_graph(conn, run_id: str, out_dir: str | Path) -> Path:
    """Write provenance chain as a node/edge graph JSON to artifacts/provenance/."""
    out_dir = Path(out_dir)
    rows = conn.execute(
        "SELECT event_id, entry_id, event_type, session_id, turn_id, "
        "agent_id, chain_hash, confidence_after, trust_after, toxicity_after, created_at "
        "FROM provenance_events WHERE run_id = ? ORDER BY created_at",
        [run_id],
    ).fetchall()
    cols = ["event_id", "entry_id", "event_type", "session_id", "turn_id",
            "agent_id", "chain_hash", "confidence_after", "trust_after",
            "toxicity_after", "created_at"]
    events = [dict(zip(cols, r)) for r in rows]

    # Build nodes (memory entries) and edges (provenance events linking them)
    entry_ids = {e["entry_id"] for e in events}
    nodes = [{"id": eid, "type": "memory_entry"} for eid in sorted(entry_ids)]
    edges = [
        {
            "source": e["entry_id"],
            "event_id": e["event_id"],
            "event_type": e["event_type"],
            "session_id": e["session_id"],
            "chain_hash": e["chain_hash"],
        }
        for e in events
    ]

    graph = {"run_id": run_id, "nodes": nodes, "edges": edges, "events": events}
    out_path = out_dir / f"{run_id}_chain.json"
    out_path.write_text(_dump(graph), encoding="utf-8")
    return out_path


def write_governance_events(conn, run_id: str, out_dir: str | Path) -> Path:
    """Write governance actions for a run to artifacts/exports/{run_id}_governance.json.

    In v1 the governance_actions table is empty; this produces an empty list,
    which is correct.
    """
    out_dir = Path(out_dir)
    try:
        rows = conn.execute(
            "SELECT * FROM governance_actions WHERE run_id = ?", [run_id]
        ).fetchall()
        desc = conn.execute(
            "SELECT * FROM governance_actions WHERE run_id = ? LIMIT 0", [run_id]
        ).description or []
        col_names = [d[0] for d in desc]
        events = [dict(zip(col_names, r)) for r in rows]
    except Exception:
        events = []

    data = {"run_id": run_id, "governance_events": events}
    out_path = out_dir / f"{run_id}_governance.json"
    out_path.write_text(_dump(data), encoding="utf-8")
    return out_path
