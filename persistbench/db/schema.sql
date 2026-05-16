-- persistbench/db/schema.sql

-- =================================================================
-- CORE TABLES (v1 -- required for experiments to run)
-- =================================================================

-- ---- RUNS -------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    benchmark_ver   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    defense_name    TEXT NOT NULL,
    defense_ver     TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    suite           TEXT NOT NULL,      -- SBMP | TSCC | CACP | ALL
    horizon         TEXT NOT NULL,      -- short | medium | long
    seed            INTEGER NOT NULL,
    scenario_count  INTEGER,
    status          TEXT NOT NULL DEFAULT 'running',
    notes           TEXT
);

-- ---- SCENARIOS --------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id     TEXT NOT NULL,
    suite           TEXT NOT NULL,
    variant         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    difficulty      TEXT NOT NULL,      -- easy | medium | hard
    session_count   INTEGER NOT NULL,
    fragment_count  INTEGER,
    attack_class    TEXT NOT NULL,
    benchmark_ver   TEXT NOT NULL,
    PRIMARY KEY (scenario_id, benchmark_ver)
);

-- ---- SESSIONS AND TURNS -----------------------------------------
-- Design ref: section 32.2 (session orchestration), 35.3 (replay engine)
CREATE TABLE IF NOT EXISTS sessions (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    is_attack_session   BOOLEAN NOT NULL DEFAULT FALSE,
    is_trigger_session  BOOLEAN NOT NULL DEFAULT FALSE,
    is_probe_session    BOOLEAN NOT NULL DEFAULT FALSE,
    turn_count          INTEGER,
    memory_entry_count  INTEGER,
    memory_risk_score   DOUBLE,         -- section 29.3
    bdi_value           DOUBLE,         -- section 24.4 -- computed per probe session
    safety_score        DOUBLE,         -- section 24.5
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    PRIMARY KEY (run_id, scenario_id, session_id)
);

CREATE TABLE IF NOT EXISTS turns (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    turn_id             INTEGER NOT NULL,
    role                TEXT NOT NULL,  -- user | assistant | system
    is_benign           BOOLEAN,
    is_trigger          BOOLEAN DEFAULT FALSE,
    is_probe            BOOLEAN DEFAULT FALSE,
    fragment_id         TEXT,           -- null if benign turn
    content_hash        TEXT NOT NULL,
    agent_response_hash TEXT,
    tool_calls_count    INTEGER DEFAULT 0,
    defense_flags_count INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, scenario_id, session_id, turn_id)
);

-- ---- MEMORY ENTRIES ---------------------------------------------
-- Design ref: section 22.2 (all seven lifecycle stages)
CREATE TABLE IF NOT EXISTS memory_entries (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    entry_id            TEXT NOT NULL,
    created_session     INTEGER NOT NULL,
    created_turn        INTEGER NOT NULL,
    content_hash        TEXT NOT NULL,
    lifecycle_stage     TEXT NOT NULL,  -- created | reinforced | mutated
                                        -- | conflicted | decayed | archived | deleted
    confidence          DOUBLE NOT NULL,
    trust_score         DOUBLE NOT NULL,
    toxicity_score      DOUBLE NOT NULL DEFAULT 0.0,
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    mutation_count      INTEGER NOT NULL DEFAULT 0,
    is_adversarial      BOOLEAN,        -- set by oracle after run
    adversarial_fragment_id TEXT,
    last_updated_session INTEGER,
    content_embedding   BLOB,           -- V2: L2-normalized 384-d float32 (all-MiniLM-L6-v2)
    PRIMARY KEY (run_id, scenario_id, entry_id)
);

-- ---- PROVENANCE -------------------------------------------------
-- Design ref: section 26.2 (ProvenanceEvent dataclass)
-- APPEND-ONLY. Never UPDATE or DELETE rows here.
CREATE TABLE IF NOT EXISTS provenance_events (
    event_id            TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    turn_id             INTEGER,
    agent_id            TEXT NOT NULL,
    entry_id            TEXT NOT NULL,
    event_type          TEXT NOT NULL,  -- create | reinforce | mutate
                                        -- | consolidate | quarantine | delete
    source_prompt_hash  TEXT,
    confidence_before   DOUBLE,
    confidence_after    DOUBLE,
    trust_before        DOUBLE,
    trust_after         DOUBLE,
    toxicity_before     DOUBLE,
    toxicity_after      DOUBLE,
    chain_hash          TEXT,           -- SHA-256(prev_chain_hash + event content)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- METRICS ----------------------------------------------------
-- Design ref: section 10 (APS/RLS/UPS), section 25 (extended CEP metrics)
CREATE TABLE IF NOT EXISTS scenario_metrics (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    aps             DOUBLE,
    rls             DOUBLE,
    ups             DOUBLE,
    ps_10           DOUBLE,
    ps_50           DOUBLE,
    chl             DOUBLE,
    bdi_10          DOUBLE,
    bdi_50          DOUBLE,
    leakage_rate    DOUBLE,
    fss             DOUBLE,
    cra             DOUBLE,
    mts_mean        DOUBLE,
    prs_mean        DOUBLE,
    ass_50          DOUBLE,
    res_mid         DOUBLE,
    attack_detected         BOOLEAN,
    detection_session       INTEGER,
    recovery_session        INTEGER,
    flags_emitted           INTEGER,
    false_positives         INTEGER,
    clean_state_achieved    BOOLEAN,
    composite_score         DOUBLE,
    PRIMARY KEY (run_id, scenario_id)
);

-- ---- DEFENSE FLAGS ----------------------------------------------
-- Design ref: section 6.4 (DefenseFlag)
CREATE TABLE IF NOT EXISTS defense_flags (
    flag_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    turn_id         INTEGER,
    tool_call_id    TEXT,
    agent_id        TEXT,
    threat_class    TEXT NOT NULL,      -- SBMP | TSCC | CACP | unknown
    confidence      DOUBLE NOT NULL,
    action          TEXT NOT NULL,      -- allow | block | quarantine | sanitize | flag
    is_true_positive BOOLEAN,
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =================================================================
-- OPTIONAL TABLES (v2 -- schema defined now, implement writers later)
-- =================================================================

-- run tracking (supports parallel execution scheduling)
CREATE TABLE IF NOT EXISTS run_scenarios (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    scenario_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    PRIMARY KEY (run_id, scenario_id)
);

-- point-in-time snapshots for trust evolution charts (section 37.3 V5)
CREATE TABLE IF NOT EXISTS memory_entry_snapshots (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    confidence      DOUBLE NOT NULL,
    trust_score     DOUBLE NOT NULL,
    toxicity_score  DOUBLE NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    embedding       BLOB,               -- V2: per-session L2-normalized 384-d float32
    PRIMARY KEY (run_id, scenario_id, entry_id, session_id)
);

-- adversarial vs benign conflict resolution records (section 25.7 CRA)
CREATE TABLE IF NOT EXISTS memory_conflicts (
    conflict_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    entry_id_a      TEXT NOT NULL,
    entry_id_b      TEXT NOT NULL,
    winner_entry_id TEXT NOT NULL,
    resolution_method TEXT,
    trust_a         DOUBLE,
    trust_b         DOUBLE,
    benign_entry_id TEXT,
    cra_correct     BOOLEAN
);

-- consolidation lineage DAG (section 26.3)
CREATE TABLE IF NOT EXISTS provenance_lineage (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    child_entry_id  TEXT NOT NULL,
    parent_entry_id TEXT NOT NULL,
    PRIMARY KEY (run_id, scenario_id, child_entry_id, parent_entry_id)
);

-- soft/hard/verified/forensic deletion certificates (section 27.2)
CREATE TABLE IF NOT EXISTS deletion_records (
    run_id                  TEXT NOT NULL,
    scenario_id             TEXT NOT NULL,
    entry_id                TEXT NOT NULL,
    deletion_event_id       TEXT NOT NULL,
    deletion_level          TEXT NOT NULL,  -- soft | hard | verified | forensic
    verification_status     TEXT NOT NULL,  -- verified | partial | failed | pending
    deletion_certificate_hash TEXT,
    PRIMARY KEY (run_id, scenario_id, entry_id)
);

-- per-suite aggregation for leaderboard (section 10.5, 36.5)
CREATE TABLE IF NOT EXISTS suite_metrics (
    run_id          TEXT NOT NULL,
    suite           TEXT NOT NULL,
    aps_mean        DOUBLE,
    aps_std         DOUBLE,
    rls_mean        DOUBLE,
    rls_std         DOUBLE,
    ups             DOUBLE,
    composite_score DOUBLE,
    scenario_count  INTEGER,
    PRIMARY KEY (run_id, suite)
);

-- governance actions triggered by OGF (section 29.5)
CREATE TABLE IF NOT EXISTS governance_actions (
    action_id       TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    action_type     TEXT NOT NULL,
    triggered_by    TEXT NOT NULL,
    mrs_at_trigger  DOUBLE,
    entry_id        TEXT,
    rollback_target_session INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- per-probe raw records for BDI computation (section 24.4)
CREATE TABLE IF NOT EXISTS behavioral_probes (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    probe_id        TEXT NOT NULL,
    probe_domain    TEXT NOT NULL,
    probe_type      TEXT NOT NULL,
    response_hash   TEXT NOT NULL,
    action_taken    TEXT,
    safety_passed   BOOLEAN,
    PRIMARY KEY (run_id, scenario_id, session_id, probe_id)
);

-- FVS-1 through FVS-15 forgetting validation results (section 27.4)
CREATE TABLE IF NOT EXISTS forgetting_validation (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,
    fvs_test_id     TEXT NOT NULL,
    sessions_after_deletion INTEGER NOT NULL,
    passed          BOOLEAN NOT NULL,
    resurfaced_content_hash TEXT,
    resurfacing_pathway TEXT,
    PRIMARY KEY (run_id, scenario_id, entry_id, fvs_test_id)
);

-- =================================================================
-- V3 TABLES — Semantic Consolidation & Archive Persistence
-- =================================================================

-- V3.1: Derived memory summaries produced by the consolidation engine
CREATE TABLE IF NOT EXISTS memory_summaries (
    summary_id       TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    scenario_id      TEXT NOT NULL,
    created_session  INTEGER NOT NULL,
    content_hash     TEXT,
    embedding        BLOB,               -- 384-d L2-normalized float32 BLOB
    source_entry_ids TEXT[],             -- parent entry_ids
    summary_type     TEXT,               -- 'extractive' | 'abstractive' | 'latent'
    is_adversarial   BOOLEAN,
    toxicity_score   DOUBLE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V3.1: Parent-child lineage edges in the consolidation DAG
CREATE TABLE IF NOT EXISTS summary_lineage (
    edge_id       TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    scenario_id   TEXT NOT NULL,
    parent_id     TEXT NOT NULL,        -- entry_id or summary_id
    child_id      TEXT NOT NULL,        -- summary_id
    lineage_type  TEXT,                 -- 'summarize' | 'merge' | 'compress'
    session_id    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V3.1: Consolidation lifecycle events (generate / mutate / reinforce / archive)
CREATE TABLE IF NOT EXISTS consolidation_events (
    event_id      TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    scenario_id   TEXT NOT NULL,
    session_id    INTEGER NOT NULL,
    summary_id    TEXT NOT NULL,
    event_type    TEXT,                 -- 'generate' | 'mutate' | 'reinforce' | 'archive'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V3.2: Cold-storage archive of memory entries
CREATE TABLE IF NOT EXISTS archived_memory_entries (
    archive_id       TEXT PRIMARY KEY,
    entry_id         TEXT NOT NULL,
    run_id           TEXT NOT NULL,
    scenario_id      TEXT NOT NULL,
    archived_session INTEGER NOT NULL,
    archive_reason   TEXT,              -- 'age' | 'capacity' | 'explicit'
    embedding        BLOB,              -- 384-d float32 retained for semantic probing
    toxicity_score   DOUBLE,
    is_adversarial   BOOLEAN,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V3.2: Archive access events (promotion, retrieval, inspection)
CREATE TABLE IF NOT EXISTS archive_access_events (
    event_id         TEXT PRIMARY KEY,
    archive_id       TEXT NOT NULL,
    run_id           TEXT NOT NULL,
    scenario_id      TEXT NOT NULL,
    session_id       INTEGER NOT NULL,
    access_reason    TEXT,              -- 'promotion' | 'retrieval' | 'inspection'
    similarity_score DOUBLE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V3.2: Archive resurrection events — deleted entries re-entering active context
CREATE TABLE IF NOT EXISTS archive_resurrection_events (
    event_id          TEXT PRIMARY KEY,
    archive_id        TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    scenario_id       TEXT NOT NULL,
    session_id        INTEGER NOT NULL,
    trigger_query     TEXT,
    similarity_score  DOUBLE,
    was_adversarial   BOOLEAN,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- V3 INDEXES --------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_summaries_run      ON memory_summaries(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_lineage_parent     ON summary_lineage(run_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_lineage_child      ON summary_lineage(run_id, child_id);
CREATE INDEX IF NOT EXISTS idx_archived_run       ON archived_memory_entries(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_resurrections_run  ON archive_resurrection_events(run_id, scenario_id);

-- ---- V2 MIGRATION GUARDS ----------------------------------------
-- Idempotent: safe to run on any database regardless of whether V2 columns exist.
-- ADD COLUMN IF NOT EXISTS is supported in DuckDB >= 1.0.
ALTER TABLE memory_entries        ADD COLUMN IF NOT EXISTS content_embedding BLOB;
ALTER TABLE memory_entry_snapshots ADD COLUMN IF NOT EXISTS embedding        BLOB;
ALTER TABLE behavioral_probes     ADD COLUMN IF NOT EXISTS response_embedding BLOB;
ALTER TABLE scenario_metrics      ADD COLUMN IF NOT EXISTS fvs              DOUBLE;
ALTER TABLE scenario_metrics      ADD COLUMN IF NOT EXISTS rr               DOUBLE;

-- ---- INDEXES (core tables only) ---------------------------------
CREATE INDEX IF NOT EXISTS idx_sessions_run      ON sessions(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_turns_session     ON turns(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_mem_entries_run   ON memory_entries(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_entry ON provenance_events(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_sess  ON provenance_events(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_flags_run         ON defense_flags(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_metrics_composite ON scenario_metrics(run_id, composite_score DESC);
