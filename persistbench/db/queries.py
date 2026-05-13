from typing import Optional

import duckdb


# =================================================================
# CORE QUERIES (v1)
# =================================================================

def get_bdi_time_series(conn: duckdb.DuckDBPyConnection,
                        run_id: str, scenario_id: str) -> list[dict]:
    """BDI and safety score per session. Feeds LEE degradation chart (section 24.4-24.5)."""
    rows = conn.execute("""
        SELECT session_id, bdi_value, safety_score, memory_risk_score
        FROM sessions
        WHERE run_id = ? AND scenario_id = ?
        ORDER BY session_id
    """, [run_id, scenario_id]).fetchall()
    return [{"session": r[0], "bdi": r[1], "safety_score": r[2],
             "mrs": r[3]} for r in rows]


def get_scenario_metrics(conn: duckdb.DuckDBPyConnection,
                         run_id: str, scenario_id: str) -> Optional[dict]:
    """All metrics for one scenario run. Returns None if not yet written."""
    row = conn.execute("""
        SELECT aps, rls, ups, bdi_10, bdi_50, composite_score,
               attack_detected, detection_session, recovery_session,
               flags_emitted, false_positives
        FROM scenario_metrics
        WHERE run_id = ? AND scenario_id = ?
    """, [run_id, scenario_id]).fetchone()
    if row is None:
        return None
    cols = ["aps", "rls", "ups", "bdi_10", "bdi_50", "composite",
            "attack_detected", "detection_session", "recovery_session",
            "flags_emitted", "false_positives"]
    return dict(zip(cols, row))


def get_provenance_events(conn: duckdb.DuckDBPyConnection,
                          run_id: str, scenario_id: str,
                          entry_id: str) -> list[dict]:
    """Ordered provenance event log for one memory entry (section 26.2)."""
    rows = conn.execute("""
        SELECT event_id, session_id, event_type,
               confidence_before, confidence_after,
               trust_before, trust_after,
               toxicity_before, toxicity_after,
               chain_hash, created_at
        FROM provenance_events
        WHERE run_id = ? AND scenario_id = ? AND entry_id = ?
        ORDER BY created_at
    """, [run_id, scenario_id, entry_id]).fetchall()
    cols = ["event_id", "session", "event_type",
            "conf_before", "conf_after", "trust_before", "trust_after",
            "tox_before", "tox_after", "chain_hash", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_defense_summary(conn: duckdb.DuckDBPyConnection,
                        run_id: str, scenario_id: str) -> dict:
    """True-positive rate and flag counts for one scenario (section 6.4)."""
    row = conn.execute("""
        SELECT COUNT(*)                                          AS total,
               COUNT(*) FILTER (WHERE is_true_positive = TRUE)  AS true_positives,
               COUNT(*) FILTER (WHERE is_true_positive = FALSE)  AS false_positives,
               AVG(confidence)                                   AS avg_confidence
        FROM defense_flags
        WHERE run_id = ? AND scenario_id = ?
    """, [run_id, scenario_id]).fetchone()
    total, tp, fp, avg_conf = row
    tpr = (tp / total) if total else None
    return {"total": total, "true_positives": tp, "false_positives": fp,
            "tpr": tpr, "avg_confidence": avg_conf}


def get_leaderboard(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Cross-run leaderboard ordered by composite score (section 10.5, 36.5).
    Only includes runs with status='complete'."""
    rows = conn.execute("""
        SELECT r.defense_name, r.model_id, r.horizon,
               AVG(sm.aps_mean)        AS aps,
               AVG(sm.rls_mean)        AS rls,
               AVG(sm.ups)             AS ups,
               AVG(sm.composite_score) AS composite,
               COUNT(*)                AS run_count
        FROM runs r
        JOIN suite_metrics sm ON sm.run_id = r.run_id AND sm.suite = 'ALL'
        WHERE r.status = 'complete'
        GROUP BY r.defense_name, r.model_id, r.horizon
        ORDER BY composite DESC
    """).fetchall()
    cols = ["defense", "model", "horizon", "aps", "rls", "ups",
            "composite", "run_count"]
    return [dict(zip(cols, r)) for r in rows]


# =================================================================
# V2 STUBS -- require optional tables
# =================================================================

def get_trust_evolution(*args, **kwargs):
    raise NotImplementedError("trust evolution requires memory_entry_snapshots (v2)")

def get_cra(*args, **kwargs):
    raise NotImplementedError("CRA requires memory_conflicts (v2)")

def get_provenance_chain(*args, **kwargs):
    raise NotImplementedError("provenance DAG requires provenance_lineage (v2)")

def get_fvs_summary(*args, **kwargs):
    raise NotImplementedError("FVS requires forgetting_validation (v2)")
