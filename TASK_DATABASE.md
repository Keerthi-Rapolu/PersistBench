# PersistBench — Database Implementation Task

**Status:** Ready to implement  
**Owner:** Keerthi Rapolu  
**Date:** 2026-05-12  
**Depends on:** DESIGN_DOC.md (read before starting any task here)

---

## 0. Before You Start

This task doc is a **companion to DESIGN_DOC.md**, not a replacement.  
Every table and schema decision below maps directly to a design doc section.  
When a section reference appears like `→ §26`, open DESIGN_DOC.md and read that section before implementing the corresponding task.

---

## 1. Database Strategy at a Glance

PersistBench needs two storage backends. They serve completely different purposes and must not be conflated.

| Backend | Role | Already installed? |
|---|---|---|
| **DuckDB** | Benchmark artifact store, metrics analytics, provenance event log, session/turn/memory-entry storage, cross-run queries | Yes |
| **Qdrant** | Vector memory backend for agent scenarios that require semantic retrieval | No — see §4 |

DuckDB handles everything that is **relational, analytical, or append-only log-structured**.  
Qdrant handles everything that is **embedding-indexed and retrieved by semantic similarity**.

The two databases are independent. DuckDB does not call Qdrant; Qdrant does not write to DuckDB. They are wired together only at the scenario execution layer (the agent backend reads from Qdrant; the benchmark runner writes results to DuckDB).

---

## 2. DuckDB — What to Store

### 2.1 Scope decision

All of the following live in DuckDB. Read the corresponding design doc section before designing a table.

| What | Design Doc Section | Notes |
|---|---|---|
| Benchmark runs metadata | §36.4, §36.5 | Mirrors `metrics.json` schema |
| Scenario definitions (metadata only) | §6.2, §12.1 | Full YAML stays on disk |
| Per-session execution records | §32.2, §35.3 | One row per session per run |
| Per-turn execution records | §32.2, §35.3 | One row per turn per session |
| Memory entry lifecycle | §22.2 | All seven lifecycle stages |
| Provenance events | §26.2 | Append-only, chained |
| Metrics (primary + extended) | §10, §25 | APS, RLS, UPS + 10 CEP metrics |
| Defense flag events | §6.4, §10.5 | `DefenseFlag` dataclass → rows |
| Governance action events | §29.5 | Graduated action log |
| Memory conflict events | §22.2 Stage 4 | Detected contradictions |
| Behavioral probe results | §24.4 | BDI time series source |
| Forgetting validation results | §27.4 | FVS-1 through FVS-15 |

### 2.2 Schema

Run the following DDL to initialise the database. File: `persistbench/db/schema.sql`.

```sql
-- ============================================================
-- CORE BENCHMARK TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,       -- e.g. run-20260512-sbmp-gpt4o-mw-001
    benchmark_ver   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    defense_name    TEXT NOT NULL,
    defense_ver     TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    suite           TEXT NOT NULL,          -- SBMP | TSCC | CACP | ALL
    horizon         TEXT NOT NULL,          -- short | medium | long
    seed            INTEGER NOT NULL,
    scenario_count  INTEGER,
    status          TEXT NOT NULL DEFAULT 'running',  -- running | complete | failed
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id     TEXT NOT NULL,          -- e.g. sbmp-001
    suite           TEXT NOT NULL,
    variant         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    difficulty      TEXT NOT NULL,          -- easy | medium | hard
    session_count   INTEGER NOT NULL,
    fragment_count  INTEGER,                -- SBMP only
    attack_class    TEXT NOT NULL,
    benchmark_ver   TEXT NOT NULL,
    PRIMARY KEY (scenario_id, benchmark_ver)
);

CREATE TABLE IF NOT EXISTS run_scenarios (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    scenario_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending | running | complete | failed
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    PRIMARY KEY (run_id, scenario_id)
);

-- ============================================================
-- SESSION AND TURN TABLES
-- Read §32.2 and §35.3 before modifying these.
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    is_attack_session   BOOLEAN NOT NULL DEFAULT FALSE,
    is_trigger_session  BOOLEAN NOT NULL DEFAULT FALSE,
    is_probe_session    BOOLEAN NOT NULL DEFAULT FALSE,
    turn_count          INTEGER,
    memory_entry_count  INTEGER,            -- entries in store at session end
    memory_risk_score   DOUBLE,             -- MRS at session start (§29.3)
    bdi_value           DOUBLE,             -- BDI checkpoint value (§24.4)
    safety_score        DOUBLE,             -- probe safety score (§24.5)
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    PRIMARY KEY (run_id, scenario_id, session_id)
);

CREATE TABLE IF NOT EXISTS turns (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    turn_id             INTEGER NOT NULL,
    role                TEXT NOT NULL,      -- user | assistant | system
    is_benign           BOOLEAN,
    is_trigger          BOOLEAN DEFAULT FALSE,
    is_probe            BOOLEAN DEFAULT FALSE,
    fragment_id         TEXT,               -- null if benign; e.g. f1, f2
    content_hash        TEXT NOT NULL,      -- SHA-256 of turn content
    agent_response_hash TEXT,
    tool_calls_count    INTEGER DEFAULT 0,
    defense_flags_count INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, scenario_id, session_id, turn_id)
);

-- ============================================================
-- MEMORY LIFECYCLE TABLES
-- Read §22 in full before touching these.
-- ============================================================

CREATE TABLE IF NOT EXISTS memory_entries (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,          -- mem-XXXXX
    created_session INTEGER NOT NULL,
    created_turn    INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,          -- created | reinforced | mutated | conflicted
                                            -- | decayed | archived | deleted
    confidence      DOUBLE NOT NULL,
    trust_score     DOUBLE NOT NULL,
    toxicity_score  DOUBLE NOT NULL DEFAULT 0.0,
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    mutation_count  INTEGER NOT NULL DEFAULT 0,
    is_adversarial  BOOLEAN,                -- null = unknown; set by oracle post-run
    adversarial_fragment_id TEXT,           -- which fragment planted this entry
    last_updated_session INTEGER,
    PRIMARY KEY (run_id, scenario_id, entry_id)
);

-- Point-in-time snapshots of entry scores (for trust evolution charts → §37.3 V5)
CREATE TABLE IF NOT EXISTS memory_entry_snapshots (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    confidence      DOUBLE NOT NULL,
    trust_score     DOUBLE NOT NULL,
    toxicity_score  DOUBLE NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    PRIMARY KEY (run_id, scenario_id, entry_id, session_id)
);

CREATE TABLE IF NOT EXISTS memory_conflicts (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    conflict_id     TEXT PRIMARY KEY,
    session_id      INTEGER NOT NULL,
    entry_id_a      TEXT NOT NULL,
    entry_id_b      TEXT NOT NULL,
    winner_entry_id TEXT NOT NULL,
    resolution_method TEXT,                 -- trust_score | recency | confidence
    trust_a         DOUBLE,
    trust_b         DOUBLE,
    -- CRA computation: if winner = benign entry, this is a correct resolution
    -- Read §25.7 for CRA definition
    benign_entry_id TEXT,                   -- which entry is the ground-truth correct one
    cra_correct     BOOLEAN                 -- true if benign entry won
);

-- ============================================================
-- PROVENANCE TABLES
-- Read §26.2 in full. These tables implement ProvenanceRecord
-- and ProvenanceEvent dataclasses from the design doc.
-- ============================================================

CREATE TABLE IF NOT EXISTS provenance_events (
    event_id            TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    turn_id             INTEGER,
    agent_id            TEXT NOT NULL,
    entry_id            TEXT NOT NULL,      -- memory entry this event belongs to
    event_type          TEXT NOT NULL,      -- create | reinforce | mutate
                                            -- | consolidate | quarantine | delete
    source_prompt_hash  TEXT,               -- SHA-256 of prompt that caused this
    confidence_before   DOUBLE,
    confidence_after    DOUBLE,
    trust_before        DOUBLE,
    trust_after         DOUBLE,
    toxicity_before     DOUBLE,
    toxicity_after      DOUBLE,
    chain_hash          TEXT,               -- hash(previous event hash + this event)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Derived-from relationships (consolidation lineage)
CREATE TABLE IF NOT EXISTS provenance_lineage (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    child_entry_id  TEXT NOT NULL,          -- the derived/consolidated entry
    parent_entry_id TEXT NOT NULL,          -- the source entry
    PRIMARY KEY (run_id, scenario_id, child_entry_id, parent_entry_id)
);

CREATE TABLE IF NOT EXISTS deletion_records (
    run_id                  TEXT NOT NULL,
    scenario_id             TEXT NOT NULL,
    entry_id                TEXT NOT NULL,
    deletion_event_id       TEXT NOT NULL,  -- FK to provenance_events
    deletion_level          TEXT NOT NULL,  -- soft | hard | verified | forensic
    verification_status     TEXT NOT NULL,  -- verified | partial | failed | pending
    deletion_certificate_hash TEXT,         -- null if level < forensic
    PRIMARY KEY (run_id, scenario_id, entry_id)
);

-- ============================================================
-- METRICS TABLES
-- Read §10 (APS/RLS/UPS) and §25 (Extended CEP metrics) before
-- adding columns here.
-- ============================================================

CREATE TABLE IF NOT EXISTS scenario_metrics (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,

    -- Primary metrics (§10)
    aps             DOUBLE,     -- Attack Persistence Score [0,1] lower = better defense
    rls             DOUBLE,     -- Recovery Latency Score [0,1] lower = better defense
    ups             DOUBLE,     -- Utility Preservation Score [0,1] higher = better

    -- Extended CEP metrics (§25)
    ps_10           DOUBLE,     -- Persistence Score at session 10
    ps_50           DOUBLE,     -- Persistence Score at session 50 (medium horizon)
    chl             DOUBLE,     -- Contamination Half-Life (sessions)
    bdi_10          DOUBLE,     -- BDI at session 10
    bdi_50          DOUBLE,     -- BDI at session 50
    leakage_rate    DOUBLE,     -- LR
    fss             DOUBLE,     -- Forgetting Success Score
    cra             DOUBLE,     -- Conflict Resolution Accuracy
    mts_mean        DOUBLE,     -- mean Memory Trustworthiness Score
    prs_mean        DOUBLE,     -- mean Provenance Reliability Score
    ass_50          DOUBLE,     -- Alignment Stability Score at session 50
    res_mid         DOUBLE,     -- Reinforcement Escalation Score at midpoint

    -- Detection details
    attack_detected         BOOLEAN,
    detection_session       INTEGER,        -- null if not detected
    recovery_session        INTEGER,        -- null if never recovered
    flags_emitted           INTEGER,
    false_positives         INTEGER,
    clean_state_achieved    BOOLEAN,

    -- Composite (§10.4)
    composite_score DOUBLE,

    PRIMARY KEY (run_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS suite_metrics (
    run_id          TEXT NOT NULL,
    suite           TEXT NOT NULL,          -- SBMP | TSCC | CACP | ALL
    aps_mean        DOUBLE,
    aps_std         DOUBLE,
    rls_mean        DOUBLE,
    rls_std         DOUBLE,
    ups             DOUBLE,
    composite_score DOUBLE,
    scenario_count  INTEGER,
    PRIMARY KEY (run_id, suite)
);

-- ============================================================
-- DEFENSE FLAG AND GOVERNANCE TABLES
-- Read §6.4 (DefensePlugin / DefenseFlag) and §29.5 (governance
-- action table) before modifying these.
-- ============================================================

CREATE TABLE IF NOT EXISTS defense_flags (
    flag_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    turn_id         INTEGER,
    tool_call_id    TEXT,
    agent_id        TEXT,
    threat_class    TEXT NOT NULL,          -- SBMP | TSCC | CACP | unknown
    confidence      DOUBLE NOT NULL,
    action          TEXT NOT NULL,          -- allow | block | quarantine | sanitize | flag
    is_true_positive BOOLEAN,              -- set by oracle post-run
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance_actions (
    action_id       TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    action_type     TEXT NOT NULL,          -- log | alert | flag | quarantine
                                            -- | freeze | rollback | reset
    triggered_by    TEXT NOT NULL,          -- mrs_threshold | content_anomaly
                                            -- | provenance_anomaly | behavioral_drift
    mrs_at_trigger  DOUBLE,
    entry_id        TEXT,                   -- affected memory entry (if applicable)
    rollback_target_session INTEGER,        -- set if action = rollback
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- BEHAVIORAL PROBE TABLE
-- Source data for BDI computation (§24.4) and Safety Degradation
-- Curves (§24.5). One row per probe query per session.
-- ============================================================

CREATE TABLE IF NOT EXISTS behavioral_probes (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    probe_id        TEXT NOT NULL,          -- from Q_probe fixed set
    probe_domain    TEXT NOT NULL,          -- software | financial | research
                                            -- | healthcare | enterprise
    probe_type      TEXT NOT NULL,          -- bdi | safety
    response_hash   TEXT NOT NULL,
    action_taken    TEXT,                   -- tool calls or refusal classification
    safety_passed   BOOLEAN,               -- for safety probes only
    PRIMARY KEY (run_id, scenario_id, session_id, probe_id)
);

-- ============================================================
-- FORGETTING VALIDATION TABLE
-- Read §27.4 (FVS-1 through FVS-15) before touching this.
-- ============================================================

CREATE TABLE IF NOT EXISTS forgetting_validation (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,          -- the entry that was deleted
    fvs_test_id     TEXT NOT NULL,          -- FVS-1 through FVS-15
    sessions_after_deletion INTEGER NOT NULL,
    passed          BOOLEAN NOT NULL,
    resurfaced_content_hash TEXT,           -- set if passed = false
    resurfacing_pathway TEXT,               -- consolidation | archive | embedding_ghost
                                            -- | semantic_neighbor | shadow_memory | null
    PRIMARY KEY (run_id, scenario_id, entry_id, fvs_test_id)
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_turns_scenario    ON turns(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_mem_entries_run   ON memory_entries(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_entry ON provenance_events(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_sess  ON provenance_events(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_flags_run         ON defense_flags(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_probes_session    ON behavioral_probes(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_fvs_entry         ON forgetting_validation(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_metrics_composite ON scenario_metrics(run_id, composite_score DESC);
```

### 2.3 Initialisation helper

File: `persistbench/db/init.py`

```python
import duckdb
from pathlib import Path

DB_PATH = Path("persistbench.duckdb")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(db_path))
    conn.execute(SCHEMA_PATH.read_text())   # idempotent — CREATE IF NOT EXISTS
    return conn
```

---

## 3. Key DuckDB Queries (implement these as named queries / views)

These queries directly feed the metrics layer and dashboard (→ §36.2, §37.3).  
Implement each as a function in `persistbench/db/queries.py`.

### 3.1 BDI time series (→ §24.4, dashboard V2)

```sql
SELECT
    session_id,
    bdi_value,
    safety_score,
    memory_risk_score
FROM sessions
WHERE run_id = ? AND scenario_id = ?
ORDER BY session_id;
```

### 3.2 Contamination Half-Life data (→ §25.3)

Returns per-session adversarial activation probability — pass to Python for curve fitting.

```sql
SELECT
    s.session_id,
    COUNT(df.flag_id) FILTER (WHERE df.is_true_positive = TRUE) AS tp_flags,
    COUNT(df.flag_id)                                            AS total_flags,
    s.memory_risk_score
FROM sessions s
LEFT JOIN defense_flags df
    ON df.run_id = s.run_id
   AND df.scenario_id = s.scenario_id
   AND df.session_id = s.session_id
WHERE s.run_id = ? AND s.scenario_id = ?
GROUP BY s.session_id, s.memory_risk_score
ORDER BY s.session_id;
```

### 3.3 Trust evolution for a specific memory entry (→ §37.3 V5)

```sql
SELECT session_id, confidence, trust_score, toxicity_score, lifecycle_stage
FROM memory_entry_snapshots
WHERE run_id = ? AND scenario_id = ? AND entry_id = ?
ORDER BY session_id;
```

### 3.4 Conflict Resolution Accuracy (→ §25.7)

```sql
SELECT
    COUNT(*) FILTER (WHERE cra_correct = TRUE)  AS correct_resolutions,
    COUNT(*)                                     AS total_conflicts,
    AVG(cra_correct::INTEGER)                   AS cra
FROM memory_conflicts
WHERE run_id = ? AND scenario_id = ?;
```

### 3.5 Provenance chain for an entry (→ §26.3)

Recursive CTE — works in DuckDB.

```sql
WITH RECURSIVE chain AS (
    SELECT child_entry_id, parent_entry_id, 1 AS depth
    FROM provenance_lineage
    WHERE run_id = ? AND scenario_id = ? AND child_entry_id = ?

    UNION ALL

    SELECT pl.child_entry_id, pl.parent_entry_id, c.depth + 1
    FROM provenance_lineage pl
    JOIN chain c ON pl.child_entry_id = c.parent_entry_id
    WHERE pl.run_id = ? AND pl.scenario_id = ?
)
SELECT * FROM chain ORDER BY depth;
```

### 3.6 Cross-run leaderboard (→ §10.5, §36.5)

```sql
SELECT
    r.defense_name,
    r.model_id,
    r.horizon,
    AVG(sm.aps_mean)        AS aps,
    AVG(sm.rls_mean)        AS rls,
    AVG(sm.ups)             AS ups,
    AVG(sm.composite_score) AS composite
FROM runs r
JOIN suite_metrics sm ON sm.run_id = r.run_id AND sm.suite = 'ALL'
WHERE r.status = 'complete'
GROUP BY r.defense_name, r.model_id, r.horizon
ORDER BY composite DESC;
```

### 3.7 Forgetting Validation summary (→ §27.5)

```sql
SELECT
    fvs_test_id,
    COUNT(*) FILTER (WHERE passed = FALSE)  AS failures,
    COUNT(*)                                 AS total,
    AVG(passed::INTEGER)                    AS pass_rate,
    COUNT(DISTINCT resurfacing_pathway) 
        FILTER (WHERE passed = FALSE)       AS distinct_pathways
FROM forgetting_validation
WHERE run_id = ?
GROUP BY fvs_test_id
ORDER BY fvs_test_id;
```

---

## 4. Qdrant — Vector Memory Backend

### 4.1 Do you need it?

**Yes, for some scenarios. No, for others.**

| Scenario type | Needs Qdrant? | Why |
|---|---|---|
| SBMP with `redis_episodic` memory backend | No | Episodic memory is key-value, not vector |
| SBMP with `qdrant_vector` memory backend | **Yes** | Semantic retrieval drives fragment accumulation |
| SBMP-5 (Memory Anchor Exploitation) | **Yes** | Tests embedding-space survivability → §7.3 |
| TSCC (all variants) | No | Tool-layer attack, not memory-layer |
| CACP (all variants) | No | Pipeline-layer attack |
| Retrieval Poisoning (Category 10) | **Yes** | Attack targets the embedding ranking → §23.11 |
| Context Collision Attacks (Category 7) | **Yes** | Multi-fragment semantic co-retrieval → §23.8 |
| Real-Time Observability Extensions | **Yes** | Live vector DB update monitoring → §38.2 |

If you are only implementing short-horizon SBMP scenarios with `redis_episodic` memory, you can defer Qdrant. If you are implementing any scenario that uses `qdrant_vector` in its scenario YAML, you need it.

### 4.2 Collections needed

Read §6.1 (Memory Backends) and §7.3 (SBMP-5 variant) before designing collections.

```
Collection: agent_memory_{scenario_id}_{run_id}
  Purpose:  Simulates the agent's long-term vector memory during a benchmark run.
  Vector:   1536-dim (OpenAI text-embedding-3-small) or 1024-dim (Cohere embed-v3)
  Payload fields:
    entry_id        : str
    session_id      : int
    turn_id         : int
    content         : str      (for filtering, not embedding)
    trust_score     : float
    toxicity_score  : float
    is_adversarial  : bool | null
    lifecycle_stage : str
    provenance_hash : str      (hash of ProvenanceRecord for integrity check)

Collection: memory_archive_{scenario_id}_{run_id}
  Purpose:  Cold-storage layer for decayed entries (§22.2 Stage 6).
  Same payload schema. Excluded from standard search; queried explicitly
  during FVS-7 (Archive Retrieval Test → §27.4).
```

One collection pair per (scenario, run). Drop both collections when the run completes and artifacts have been written to DuckDB.

### 4.3 Install and initialise

```bash
# Install Qdrant locally (Docker)
docker pull qdrant/qdrant
docker run -p 6333:6333 -v $(pwd)/qdrant_data:/qdrant/storage qdrant/qdrant

# Python client
pip install qdrant-client
```

```python
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

def create_memory_collection(client: QdrantClient, scenario_id: str, run_id: str):
    name = f"agent_memory_{scenario_id}_{run_id}"
    client.recreate_collection(
        collection_name=name,
        vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
    )
    return name
```

### 4.4 Relationship to DuckDB

Qdrant stores live embedding vectors during scenario execution.  
DuckDB stores the **results** and **provenance** of those operations after execution.

The bridge is `entry_id` — a memory entry's `entry_id` appears in both stores.  
After a scenario run completes, write memory entry scores and provenance events  
to DuckDB (using `entry_id` as the join key), then delete the Qdrant collection.

DuckDB is the permanent record. Qdrant is the runtime working store.

---

## 5. File Layout

```
persistbench/
├── db/
│   ├── __init__.py
│   ├── schema.sql          ← DuckDB DDL (§2.2 above)
│   ├── init.py             ← get_connection() helper
│   ├── queries.py          ← named query functions (§2.3 above)
│   └── writers.py          ← functions that INSERT from benchmark runner output
├── memory/
│   ├── backends/
│   │   ├── redis_episodic.py
│   │   ├── qdrant_vector.py    ← Qdrant client wrapper (§4.3)
│   │   ├── in_context.py
│   │   └── base.py
│   └── provenance.py           ← ProvenanceRecord, ProvenanceEvent dataclasses (→ §26.2)
```

---

## 6. Task Checklist

### 6.1 DuckDB — must-have for initial benchmark

- [ ] Write `schema.sql` with all tables from §2.2
- [ ] Write `init.py` — `get_connection()` that runs schema on first connect
- [ ] Write `writers.py` — one `write_*` function per table
  - [ ] `write_run()`
  - [ ] `write_session()`
  - [ ] `write_turn()`
  - [ ] `write_memory_entry()`
  - [ ] `write_memory_entry_snapshot()` — called at each session checkpoint
  - [ ] `write_provenance_event()` — append-only; validate chain hash
  - [ ] `write_provenance_lineage()` — on each consolidation event
  - [ ] `write_defense_flag()`
  - [ ] `write_governance_action()`
  - [ ] `write_behavioral_probe()`
  - [ ] `write_forgetting_validation()` — after each FVS test
  - [ ] `write_scenario_metrics()` — called by Evaluation Engine (→ §36.2 Layer 2)
  - [ ] `write_suite_metrics()`
- [ ] Write `queries.py` — named functions from §2.3 above
- [ ] Write unit tests that insert a minimal run and assert all query outputs are non-empty

### 6.2 Qdrant — needed for vector-memory scenarios

- [ ] Confirm which scenarios in initial release use `qdrant_vector` backend
- [ ] If any: set up Docker Compose entry for Qdrant
- [ ] Write `qdrant_vector.py` — implements `MemoryBackend` interface (→ §6.3 of design doc)
- [ ] Write `create_memory_collection()` / `drop_memory_collection()` lifecycle helpers
- [ ] Write bridge function: `flush_qdrant_to_duckdb(scenario_id, run_id)` — reads all
      payloads from Qdrant collection and bulk-inserts into `memory_entries`

### 6.3 Defer for later

- [ ] Neo4j / Amazon Neptune for RTOE live provenance DAG (→ §38.2)  
      *Not needed for initial benchmark; DuckDB provenance tables cover the offline case.*
- [ ] Kafka / Pulsar ingestion for Phase 3 streaming (→ §31.4)  
      *Not needed until real-time observability track is started.*

---

## 7. Open Questions

| # | Question | Where to look |
|---|---|---|
| Q1 | Which SBMP scenarios in v1.0 use `qdrant_vector` vs `redis_episodic`? | Check scenario YAML `memory.backend` field; design doc §7.6 example uses `redis_episodic` |
| Q2 | Embedding model to use for Qdrant? | Design doc does not specify; decide between `text-embedding-3-small` (1536-d, OpenAI) and `all-MiniLM-L6-v2` (384-d, local, no API cost) |
| Q3 | Chain hash algorithm for provenance events? | Design doc §26.2 references cryptographic chaining; SHA-256(prev_hash \|\| event_json) is the natural choice |
| Q4 | How often to snapshot `memory_entry_snapshots`? | Every session (safe default) vs every N sessions (reduces storage). See §37.3 V5 — dashboard needs at least session-granularity |
| Q5 | DuckDB file vs in-memory for CI runs? | Use `:memory:` for unit tests, file for integration tests and production runs |

---

*For architecture context behind every decision above, read DESIGN_DOC.md.*  
*Key sections: §6 (Architecture), §22 (Memory Lifecycle), §25 (Metrics), §26 (Provenance), §29 (Governance), §35 (Replay Engine), §36 (Output Architecture).*
