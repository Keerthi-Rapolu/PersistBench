import hashlib
from datetime import datetime, timezone
from typing import Optional

import duckdb


# =================================================================
# CORE WRITERS (v1)
# =================================================================

def write_run(conn: duckdb.DuckDBPyConnection, *,
              run_id: str, benchmark_ver: str, defense_name: str,
              defense_ver: str, model_id: str, suite: str,
              horizon: str, seed: int, notes: str = None) -> None:
    conn.execute("""
        INSERT INTO runs (run_id, benchmark_ver, defense_name, defense_ver,
                          model_id, suite, horizon, seed, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, benchmark_ver, defense_name, defense_ver,
          model_id, suite, horizon, seed, notes])


def write_scenario(conn: duckdb.DuckDBPyConnection, *,
                   scenario_id: str, suite: str, variant: str,
                   domain: str, difficulty: str, session_count: int,
                   attack_class: str, benchmark_ver: str,
                   fragment_count: int = None) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO scenarios
        (scenario_id, suite, variant, domain, difficulty,
         session_count, fragment_count, attack_class, benchmark_ver)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [scenario_id, suite, variant, domain, difficulty,
          session_count, fragment_count, attack_class, benchmark_ver])


def write_session(conn: duckdb.DuckDBPyConnection, *,
                  run_id: str, scenario_id: str, session_id: int,
                  is_attack_session: bool = False,
                  is_trigger_session: bool = False,
                  is_probe_session: bool = False,
                  turn_count: int = None,
                  memory_entry_count: int = None,
                  memory_risk_score: float = None,
                  bdi_value: float = None,
                  safety_score: float = None) -> None:
    conn.execute("""
        INSERT INTO sessions
        (run_id, scenario_id, session_id, is_attack_session,
         is_trigger_session, is_probe_session, turn_count,
         memory_entry_count, memory_risk_score, bdi_value,
         safety_score, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, session_id, is_attack_session,
          is_trigger_session, is_probe_session, turn_count,
          memory_entry_count, memory_risk_score, bdi_value,
          safety_score, datetime.now(timezone.utc)])


def write_turn(conn: duckdb.DuckDBPyConnection, *,
               run_id: str, scenario_id: str, session_id: int,
               turn_id: int, role: str, content_hash: str,
               is_benign: bool = None, is_trigger: bool = False,
               is_probe: bool = False, fragment_id: str = None,
               agent_response_hash: str = None,
               tool_calls_count: int = 0,
               defense_flags_count: int = 0) -> None:
    conn.execute("""
        INSERT INTO turns
        (run_id, scenario_id, session_id, turn_id, role, content_hash,
         is_benign, is_trigger, is_probe, fragment_id,
         agent_response_hash, tool_calls_count, defense_flags_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, session_id, turn_id, role, content_hash,
          is_benign, is_trigger, is_probe, fragment_id,
          agent_response_hash, tool_calls_count, defense_flags_count])


def write_memory_entry(conn: duckdb.DuckDBPyConnection, *,
                       run_id: str, scenario_id: str, entry_id: str,
                       created_session: int, created_turn: int,
                       content_hash: str, lifecycle_stage: str,
                       confidence: float, trust_score: float,
                       toxicity_score: float = 0.0,
                       reinforcement_count: int = 0,
                       mutation_count: int = 0,
                       is_adversarial: bool = None,
                       adversarial_fragment_id: str = None,
                       content_embedding: bytes = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO memory_entries
        (run_id, scenario_id, entry_id, created_session, created_turn,
         content_hash, lifecycle_stage, confidence, trust_score,
         toxicity_score, reinforcement_count, mutation_count,
         is_adversarial, adversarial_fragment_id, last_updated_session,
         content_embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, created_session, created_turn,
          content_hash, lifecycle_stage, confidence, trust_score,
          toxicity_score, reinforcement_count, mutation_count,
          is_adversarial, adversarial_fragment_id, created_session,
          content_embedding])


def _compute_chain_hash(prev_hash: Optional[str], event_id: str,
                        entry_id: str, event_type: str,
                        session_id: int) -> str:
    payload = f"{prev_hash or ''}|{event_id}|{entry_id}|{event_type}|{session_id}"
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def get_last_chain_hash(conn: duckdb.DuckDBPyConnection,
                        run_id: str, scenario_id: str) -> Optional[str]:
    row = conn.execute("""
        SELECT chain_hash FROM provenance_events
        WHERE run_id = ? AND scenario_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, [run_id, scenario_id]).fetchone()
    return row[0] if row else None


def write_provenance_event(conn: duckdb.DuckDBPyConnection, *,
                           event_id: str, run_id: str, scenario_id: str,
                           session_id: int, agent_id: str, entry_id: str,
                           event_type: str, turn_id: int = None,
                           source_prompt_hash: str = None,
                           confidence_before: float = None,
                           confidence_after: float = None,
                           trust_before: float = None,
                           trust_after: float = None,
                           toxicity_before: float = None,
                           toxicity_after: float = None) -> None:
    prev_hash = get_last_chain_hash(conn, run_id, scenario_id)
    chain_hash = _compute_chain_hash(prev_hash, event_id, entry_id,
                                     event_type, session_id)
    conn.execute("""
        INSERT INTO provenance_events
        (event_id, run_id, scenario_id, session_id, turn_id, agent_id,
         entry_id, event_type, source_prompt_hash,
         confidence_before, confidence_after,
         trust_before, trust_after, toxicity_before, toxicity_after,
         chain_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [event_id, run_id, scenario_id, session_id, turn_id, agent_id,
          entry_id, event_type, source_prompt_hash,
          confidence_before, confidence_after,
          trust_before, trust_after, toxicity_before, toxicity_after,
          chain_hash])


def write_defense_flag(conn: duckdb.DuckDBPyConnection, *,
                       flag_id: str, run_id: str, scenario_id: str,
                       session_id: int, threat_class: str,
                       confidence: float, action: str,
                       turn_id: int = None, tool_call_id: str = None,
                       agent_id: str = None,
                       is_true_positive: bool = None) -> None:
    conn.execute("""
        INSERT INTO defense_flags
        (flag_id, run_id, scenario_id, session_id, turn_id,
         tool_call_id, agent_id, threat_class, confidence, action,
         is_true_positive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [flag_id, run_id, scenario_id, session_id, turn_id,
          tool_call_id, agent_id, threat_class, confidence, action,
          is_true_positive])


def write_scenario_metrics(conn: duckdb.DuckDBPyConnection, *,
                           run_id: str, scenario_id: str,
                           aps: float = None, rls: float = None,
                           ups: float = None, ps_10: float = None,
                           ps_50: float = None, chl: float = None,
                           bdi_10: float = None, bdi_50: float = None,
                           leakage_rate: float = None, fss: float = None,
                           cra: float = None, mts_mean: float = None,
                           prs_mean: float = None, ass_50: float = None,
                           res_mid: float = None,
                           attack_detected: bool = None,
                           detection_session: int = None,
                           recovery_session: int = None,
                           flags_emitted: int = None,
                           false_positives: int = None,
                           clean_state_achieved: bool = None,
                           composite_score: float = None,
                           fvs: float = None,
                           rr: float = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO scenario_metrics
        (run_id, scenario_id, aps, rls, ups, ps_10, ps_50, chl,
         bdi_10, bdi_50, leakage_rate, fss, cra, mts_mean, prs_mean,
         ass_50, res_mid, attack_detected, detection_session,
         recovery_session, flags_emitted, false_positives,
         clean_state_achieved, composite_score, fvs, rr)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, aps, rls, ups, ps_10, ps_50, chl,
          bdi_10, bdi_50, leakage_rate, fss, cra, mts_mean, prs_mean,
          ass_50, res_mid, attack_detected, detection_session,
          recovery_session, flags_emitted, false_positives,
          clean_state_achieved, composite_score, fvs, rr])


def write_suite_metrics(conn: duckdb.DuckDBPyConnection, *,
                        run_id: str, suite: str,
                        aps_mean: float, aps_std: float,
                        rls_mean: float, rls_std: float,
                        ups: float, composite_score: float,
                        scenario_count: int) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO suite_metrics
        (run_id, suite, aps_mean, aps_std, rls_mean, rls_std,
         ups, composite_score, scenario_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, suite, aps_mean, aps_std, rls_mean, rls_std,
          ups, composite_score, scenario_count])


# =================================================================
# LATE-STAGE V1 WRITERS (promoted from v2)
# =================================================================

def write_memory_entry_snapshot(conn: duckdb.DuckDBPyConnection, *,
                                run_id: str, scenario_id: str,
                                entry_id: str, session_id: int,
                                confidence: float, trust_score: float,
                                toxicity_score: float,
                                lifecycle_stage: str,
                                embedding: bytes = None) -> None:
    """Record a point-in-time snapshot of a memory entry's scores.

    Called once per memory entry per session to power trust-evolution
    charts in the dashboard.
    """
    conn.execute("""
        INSERT OR REPLACE INTO memory_entry_snapshots
        (run_id, scenario_id, entry_id, session_id,
         confidence, trust_score, toxicity_score, lifecycle_stage,
         embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, session_id,
          confidence, trust_score, toxicity_score, lifecycle_stage,
          embedding])


# =================================================================
# V2 STUBS -- implement when optional tables are needed
# =================================================================

def write_run_scenario(*args, **kwargs):
    raise NotImplementedError("run_scenarios is a v2 table")

def update_run_scenario_status(*args, **kwargs):
    raise NotImplementedError("run_scenarios is a v2 table")


def write_behavioral_probe(conn: duckdb.DuckDBPyConnection, *,
                           run_id: str, scenario_id: str,
                           session_id: int, probe_id: str,
                           probe_domain: str, probe_type: str,
                           response_text: str,
                           safety_passed: bool = None,
                           action_taken: str = None) -> None:
    """Record an agent's probe response with its embedding for BDI_sem computation.

    response_embedding is always written so get_bdi_semantic() can compute
    cosine drift from the baseline (earliest probe session) to any later session.
    Design ref: §24.4 (BDI_sem = 1 − cosine(h_s, h_baseline))
    """
    import hashlib as _hashlib
    from persistbench.embeddings import encode as _encode, vec_to_bytes as _vec_to_bytes

    response_hash = "sha256:" + _hashlib.sha256(response_text.encode()).hexdigest()
    embedding = _vec_to_bytes(_encode(response_text))
    conn.execute("""
        INSERT OR REPLACE INTO behavioral_probes
        (run_id, scenario_id, session_id, probe_id, probe_domain,
         probe_type, response_hash, action_taken, safety_passed, response_embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, session_id, probe_id, probe_domain,
          probe_type, response_hash, action_taken, safety_passed, embedding])

def write_provenance_lineage(conn: duckdb.DuckDBPyConnection, *,
                             run_id: str, scenario_id: str,
                             child_entry_id: str, parent_entry_id: str) -> None:
    """Record a parent→child edge in the provenance DAG (V3.4).

    Used for multi-parent lineage (summaries that have multiple source entries).
    Silently ignores duplicate edges (idempotent).
    """
    conn.execute("""
        INSERT OR IGNORE INTO provenance_lineage
        (run_id, scenario_id, child_entry_id, parent_entry_id)
        VALUES (?, ?, ?, ?)
    """, [run_id, scenario_id, child_entry_id, parent_entry_id])


def write_deletion_record(conn: duckdb.DuckDBPyConnection, *,
                          run_id: str, scenario_id: str,
                          entry_id: str, deletion_event_id: str,
                          deletion_level: str,
                          verification_status: str = "pending",
                          deletion_certificate_hash: str = None) -> None:
    """Record a deletion attempt with its completeness level and certificate.

    deletion_level: "soft" | "hard" | "verified" | "forensic"
      soft     — removed from primary store, may persist in archives/indices
      hard     — removed from primary + indices (DuckDB + Qdrant)
      verified — removed from all stores, deletion confirmed by oracle
      forensic — verified + full audit trail retained (§27.2)
    """
    conn.execute("""
        INSERT OR REPLACE INTO deletion_records
        (run_id, scenario_id, entry_id, deletion_event_id,
         deletion_level, verification_status, deletion_certificate_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, deletion_event_id,
          deletion_level, verification_status, deletion_certificate_hash])


def write_memory_conflict(*args, **kwargs):
    raise NotImplementedError("memory_conflicts is a v2 table")

def write_governance_action(*args, **kwargs):
    raise NotImplementedError("governance_actions is a v2 table")


# =================================================================
# V3 WRITERS — Semantic Consolidation & Archive Persistence
# =================================================================

def write_memory_summary(conn: duckdb.DuckDBPyConnection, *,
                         summary_id: str, run_id: str, scenario_id: str,
                         created_session: int,
                         source_entry_ids: list,
                         summary_type: str,
                         is_adversarial: bool,
                         toxicity_score: float,
                         content_hash: str = None,
                         embedding: bytes = None) -> None:
    """Write a derived memory summary produced by the ConsolidationEngine (§V3.1)."""
    conn.execute("""
        INSERT OR REPLACE INTO memory_summaries
        (summary_id, run_id, scenario_id, created_session,
         content_hash, embedding, source_entry_ids,
         summary_type, is_adversarial, toxicity_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [summary_id, run_id, scenario_id, created_session,
          content_hash, embedding, source_entry_ids,
          summary_type, is_adversarial, toxicity_score])


def write_summary_lineage_edge(conn: duckdb.DuckDBPyConnection, *,
                                edge_id: str, run_id: str, scenario_id: str,
                                parent_id: str, child_id: str,
                                lineage_type: str, session_id: int) -> None:
    """Write a parent→child edge in the summary lineage DAG (§V3.1)."""
    conn.execute("""
        INSERT OR IGNORE INTO summary_lineage
        (edge_id, run_id, scenario_id, parent_id, child_id,
         lineage_type, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [edge_id, run_id, scenario_id, parent_id, child_id,
          lineage_type, session_id])


def write_consolidation_event(conn: duckdb.DuckDBPyConnection, *,
                               event_id: str, run_id: str, scenario_id: str,
                               session_id: int, summary_id: str,
                               event_type: str) -> None:
    """Write a consolidation lifecycle event (§V3.1).

    event_type: 'generate' | 'mutate' | 'reinforce' | 'archive'
    """
    conn.execute("""
        INSERT OR IGNORE INTO consolidation_events
        (event_id, run_id, scenario_id, session_id, summary_id, event_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [event_id, run_id, scenario_id, session_id, summary_id, event_type])


def write_archived_memory_entry(conn: duckdb.DuckDBPyConnection, *,
                                 archive_id: str, entry_id: str,
                                 run_id: str, scenario_id: str,
                                 archived_session: int,
                                 archive_reason: str = "age",
                                 embedding: bytes = None,
                                 toxicity_score: float = None,
                                 is_adversarial: bool = None) -> None:
    """Write an archived entry to the cold-storage tier (§V3.2).

    archive_reason: 'age' | 'capacity' | 'explicit'
    """
    conn.execute("""
        INSERT OR IGNORE INTO archived_memory_entries
        (archive_id, entry_id, run_id, scenario_id,
         archived_session, archive_reason, embedding,
         toxicity_score, is_adversarial)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [archive_id, entry_id, run_id, scenario_id,
          archived_session, archive_reason, embedding,
          toxicity_score, is_adversarial])


def write_archive_access_event(conn: duckdb.DuckDBPyConnection, *,
                                event_id: str, archive_id: str,
                                run_id: str, scenario_id: str,
                                session_id: int, access_reason: str,
                                similarity_score: float = None) -> None:
    """Record an access event against an archived entry (§V3.2).

    access_reason: 'promotion' | 'retrieval' | 'inspection'
    """
    conn.execute("""
        INSERT OR IGNORE INTO archive_access_events
        (event_id, archive_id, run_id, scenario_id,
         session_id, access_reason, similarity_score)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [event_id, archive_id, run_id, scenario_id,
          session_id, access_reason, similarity_score])


def write_archive_resurrection_event(conn: duckdb.DuckDBPyConnection, *,
                                      event_id: str, archive_id: str,
                                      run_id: str, scenario_id: str,
                                      session_id: int,
                                      trigger_query: str = None,
                                      similarity_score: float = None,
                                      was_adversarial: bool = None) -> None:
    """Record that an archived entry was semantically resurrected (§V3.2, FVS-6)."""
    conn.execute("""
        INSERT OR IGNORE INTO archive_resurrection_events
        (event_id, archive_id, run_id, scenario_id,
         session_id, trigger_query, similarity_score, was_adversarial)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [event_id, archive_id, run_id, scenario_id,
          session_id, trigger_query, similarity_score, was_adversarial])


def write_forgetting_validation(conn: duckdb.DuckDBPyConnection, *,
                                run_id: str, scenario_id: str,
                                entry_id: str, fvs_test_id: str,
                                sessions_after_deletion: int,
                                passed: bool,
                                resurfaced_content_hash: str = None,
                                resurfacing_pathway: str = None) -> None:
    """Record one FVS test result for a deleted memory entry (§27.4)."""
    conn.execute("""
        INSERT OR REPLACE INTO forgetting_validation
        (run_id, scenario_id, entry_id, fvs_test_id,
         sessions_after_deletion, passed, resurfaced_content_hash, resurfacing_pathway)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, fvs_test_id,
          sessions_after_deletion, passed,
          resurfaced_content_hash, resurfacing_pathway])
