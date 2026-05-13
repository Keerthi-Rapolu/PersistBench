# PersistBench — Database Implementation Tasks

**Owner:** Keerthi Rapolu  
**Updated:** 2026-05-12  
**Design reference:** DESIGN_DOC.md (open it alongside this doc)

---

## How to use this doc

Tasks are ordered by dependency — complete them top to bottom.  
Each task has exactly three parts:

- **Do:** what to create or write
- **Verify:** one command or assertion that confirms it worked
- **Design ref:** which section of DESIGN_DOC.md explains the *why*

Do not skip ahead. Tasks in Phase 2 import from Phase 1.  
Tasks in Phase 3 assume Phase 2 writers are working.

---

## Phase 0 — Decisions before you write a line of code

Two questions must be answered before implementation starts.  
They affect the schema and whether you need Qdrant at all.

---

### Task 0.1 — Confirm DuckDB version

**Do:**
```bash
python -c "import duckdb; print(duckdb.__version__)"
```

**Verify:** version is `≥ 0.10.0` (recursive CTEs and `TIMESTAMPTZ` both require this)

**If below 0.10.0:**
```bash
pip install --upgrade duckdb
```

---

### Task 0.2 — Decide: which memory backend for v1 scenarios?

Open DESIGN_DOC.md → **§7.6** (SBMP scenario YAML example).  
Look at the `memory.backend` field. It uses `redis_episodic`.

**Decision rule:**

| If v1 scenarios only use `redis_episodic` or `in_context` | → Skip Qdrant for now. Do Phase 4 last. |
| If any scenario YAML has `qdrant_vector` | → You need Qdrant. Do Phase 4 in parallel with Phase 3. |

**Write your decision here before continuing:**

```
v1 memory backend: _______________
Qdrant needed in v1: YES / NO
```

---

### Task 0.3 — Decide: embedding model for Qdrant (if needed)

Skip this task if Task 0.2 = NO.

| Option | Vector size | Cost | Requires API key |
|---|---|---|---|
| `text-embedding-3-small` (OpenAI) | 1536-d | API cost per token | Yes |
| `all-MiniLM-L6-v2` (sentence-transformers) | 384-d | Free, runs locally | No |

Pick one. Write it here:
```
Embedding model: _______________
Vector dimension: _______________
```

This affects the Qdrant collection schema in Phase 4.

---

## Phase 1 — DuckDB foundation

Everything else depends on this phase being complete.

---

### Task 1.1 — Create the db/ directory and schema file

**Do:** Create this file at `persistbench/db/schema.sql`

```sql
-- persistbench/db/schema.sql

-- ── RUNS ──────────────────────────────────────────────────────
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

-- ── SCENARIOS ─────────────────────────────────────────────────
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

CREATE TABLE IF NOT EXISTS run_scenarios (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    scenario_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    PRIMARY KEY (run_id, scenario_id)
);

-- ── SESSIONS AND TURNS ────────────────────────────────────────
-- Design ref: §32.2, §35.3
CREATE TABLE IF NOT EXISTS sessions (
    run_id              TEXT NOT NULL,
    scenario_id         TEXT NOT NULL,
    session_id          INTEGER NOT NULL,
    is_attack_session   BOOLEAN NOT NULL DEFAULT FALSE,
    is_trigger_session  BOOLEAN NOT NULL DEFAULT FALSE,
    is_probe_session    BOOLEAN NOT NULL DEFAULT FALSE,
    turn_count          INTEGER,
    memory_entry_count  INTEGER,
    memory_risk_score   DOUBLE,         -- computed by OGF (§29.3)
    bdi_value           DOUBLE,         -- BDI checkpoint (§24.4)
    safety_score        DOUBLE,         -- probe safety score (§24.5)
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
    fragment_id         TEXT,           -- e.g. f1, f2 — null if benign
    content_hash        TEXT NOT NULL,
    agent_response_hash TEXT,
    tool_calls_count    INTEGER DEFAULT 0,
    defense_flags_count INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, scenario_id, session_id, turn_id)
);

-- ── MEMORY ENTRIES ────────────────────────────────────────────
-- Design ref: §22.2 (all seven lifecycle stages)
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
    PRIMARY KEY (run_id, scenario_id, entry_id)
);

-- Point-in-time snapshots for trust evolution charts (§37.3 V5)
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
    cra_correct     BOOLEAN         -- TRUE if benign entry won (§25.7)
);

-- ── PROVENANCE ────────────────────────────────────────────────
-- Design ref: §26.2 (ProvenanceEvent dataclass)
-- This table is append-only. Never UPDATE or DELETE rows here.
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

-- Consolidation lineage (child derived from parents)
CREATE TABLE IF NOT EXISTS provenance_lineage (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    child_entry_id  TEXT NOT NULL,
    parent_entry_id TEXT NOT NULL,
    PRIMARY KEY (run_id, scenario_id, child_entry_id, parent_entry_id)
);

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

-- ── METRICS ───────────────────────────────────────────────────
-- Design ref: §10 (APS/RLS/UPS), §25 (10 extended CEP metrics)
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

-- ── DEFENSE AND GOVERNANCE EVENTS ────────────────────────────
-- Design ref: §6.4 (DefenseFlag), §29.5 (governance action table)
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

CREATE TABLE IF NOT EXISTS governance_actions (
    action_id       TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    action_type     TEXT NOT NULL,      -- log | alert | flag | quarantine
                                        -- | freeze | rollback | reset
    triggered_by    TEXT NOT NULL,
    mrs_at_trigger  DOUBLE,
    entry_id        TEXT,
    rollback_target_session INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── BEHAVIORAL PROBES ─────────────────────────────────────────
-- Design ref: §24.4 (BDI source data), §24.5 (safety score)
CREATE TABLE IF NOT EXISTS behavioral_probes (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    probe_id        TEXT NOT NULL,
    probe_domain    TEXT NOT NULL,
    probe_type      TEXT NOT NULL,      -- bdi | safety
    response_hash   TEXT NOT NULL,
    action_taken    TEXT,
    safety_passed   BOOLEAN,
    PRIMARY KEY (run_id, scenario_id, session_id, probe_id)
);

-- ── FORGETTING VALIDATION ─────────────────────────────────────
-- Design ref: §27.4 (FVS-1 through FVS-15)
CREATE TABLE IF NOT EXISTS forgetting_validation (
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    entry_id        TEXT NOT NULL,
    fvs_test_id     TEXT NOT NULL,      -- FVS-1 ... FVS-15
    sessions_after_deletion INTEGER NOT NULL,
    passed          BOOLEAN NOT NULL,
    resurfaced_content_hash TEXT,
    resurfacing_pathway TEXT,           -- consolidation | archive | embedding_ghost
                                        -- | semantic_neighbor | shadow_memory
    PRIMARY KEY (run_id, scenario_id, entry_id, fvs_test_id)
);

-- ── INDEXES ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sessions_run     ON sessions(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_turns_session    ON turns(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_mem_entries_run  ON memory_entries(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_mem_snapshots    ON memory_entry_snapshots(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_entry ON provenance_events(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_prov_events_sess  ON provenance_events(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_flags_run        ON defense_flags(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_probes_session   ON behavioral_probes(run_id, scenario_id, session_id);
CREATE INDEX IF NOT EXISTS idx_fvs_entry        ON forgetting_validation(run_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_metrics_composite ON scenario_metrics(run_id, composite_score DESC);
```

**Verify:**
```python
import duckdb
conn = duckdb.connect(":memory:")
conn.execute(open("persistbench/db/schema.sql").read())
tables = conn.execute("SHOW TABLES").fetchall()
assert len(tables) == 16, f"Expected 16 tables, got {len(tables)}: {tables}"
print("Schema OK:", [t[0] for t in tables])
```

**Design ref:** §22.2 (memory tables), §26.2 (provenance tables), §10 + §25 (metrics tables)

---

### Task 1.2 — Write the connection helper

**Do:** Create `persistbench/db/__init__.py` (empty) and `persistbench/db/init.py`

```python
# persistbench/db/init.py
import duckdb
from pathlib import Path

_SCHEMA = Path(__file__).parent / "schema.sql"
_DEFAULT_DB = Path("persistbench.duckdb")


def get_connection(db_path: Path = _DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with the schema applied.
    
    Safe to call multiple times — schema uses CREATE IF NOT EXISTS throughout.
    Pass db_path=':memory:' for tests.
    """
    conn = duckdb.connect(str(db_path))
    conn.execute(_SCHEMA.read_text())
    return conn
```

**Verify:**
```python
from persistbench.db.init import get_connection
conn = get_connection(":memory:")
result = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main'").fetchone()
assert result[0] == 16
print("Connection helper OK")
```

---

## Phase 2 — Write functions

One function per table. All live in `persistbench/db/writers.py`.  
Each function takes a connection as its first argument — no global state.

Create the file now with just the imports, then add functions one task at a time:

```python
# persistbench/db/writers.py
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
import duckdb
```

---

### Task 2.1 — write_run()

**Do:** Add to `writers.py`

```python
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
```

**Verify:**
```python
from persistbench.db.init import get_connection
from persistbench.db.writers import write_run
conn = get_connection(":memory:")
write_run(conn, run_id="test-001", benchmark_ver="1.0.0",
          defense_name="NoDefense", defense_ver="1.0.0",
          model_id="gpt-4o", suite="SBMP", horizon="short", seed=42)
row = conn.execute("SELECT run_id FROM runs WHERE run_id = 'test-001'").fetchone()
assert row[0] == "test-001"
```

---

### Task 2.2 — write_scenario() and write_run_scenario()

**Do:** Add to `writers.py`

```python
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


def write_run_scenario(conn: duckdb.DuckDBPyConnection, *,
                       run_id: str, scenario_id: str,
                       status: str = "pending") -> None:
    conn.execute("""
        INSERT INTO run_scenarios (run_id, scenario_id, status)
        VALUES (?, ?, ?)
    """, [run_id, scenario_id, status])


def update_run_scenario_status(conn: duckdb.DuckDBPyConnection, *,
                                run_id: str, scenario_id: str,
                                status: str) -> None:
    ts = datetime.now(timezone.utc)
    if status == "running":
        conn.execute("""UPDATE run_scenarios SET status=?, started_at=?
                        WHERE run_id=? AND scenario_id=?""",
                     [status, ts, run_id, scenario_id])
    else:
        conn.execute("""UPDATE run_scenarios SET status=?, finished_at=?
                        WHERE run_id=? AND scenario_id=?""",
                     [status, ts, run_id, scenario_id])
```

**Verify:**
```python
write_scenario(conn, scenario_id="sbmp-001", suite="SBMP",
               variant="direct_accumulation", domain="software_development",
               difficulty="medium", session_count=10,
               attack_class="SBMP", benchmark_ver="1.0.0", fragment_count=3)
write_run_scenario(conn, run_id="test-001", scenario_id="sbmp-001")
row = conn.execute("SELECT status FROM run_scenarios WHERE run_id='test-001'").fetchone()
assert row[0] == "pending"
```

---

### Task 2.3 — write_session()

**Do:** Add to `writers.py`

```python
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
```

**Verify:**
```python
write_session(conn, run_id="test-001", scenario_id="sbmp-001",
              session_id=1, is_attack_session=True, bdi_value=0.02)
row = conn.execute("""SELECT bdi_value FROM sessions
                      WHERE run_id='test-001' AND session_id=1""").fetchone()
assert row[0] == 0.02
```

---

### Task 2.4 — write_turn()

**Do:** Add to `writers.py`

```python
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
```

**Verify:**
```python
write_turn(conn, run_id="test-001", scenario_id="sbmp-001",
           session_id=1, turn_id=1, role="user",
           content_hash="sha256:abc123", is_benign=False, fragment_id="f1")
row = conn.execute("""SELECT fragment_id FROM turns
                      WHERE run_id='test-001' AND turn_id=1""").fetchone()
assert row[0] == "f1"
```

---

### Task 2.5 — write_memory_entry() and write_memory_entry_snapshot()

**Do:** Add to `writers.py`

```python
def write_memory_entry(conn: duckdb.DuckDBPyConnection, *,
                       run_id: str, scenario_id: str, entry_id: str,
                       created_session: int, created_turn: int,
                       content_hash: str, lifecycle_stage: str,
                       confidence: float, trust_score: float,
                       toxicity_score: float = 0.0,
                       reinforcement_count: int = 0,
                       mutation_count: int = 0,
                       is_adversarial: bool = None,
                       adversarial_fragment_id: str = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO memory_entries
        (run_id, scenario_id, entry_id, created_session, created_turn,
         content_hash, lifecycle_stage, confidence, trust_score,
         toxicity_score, reinforcement_count, mutation_count,
         is_adversarial, adversarial_fragment_id, last_updated_session)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, created_session, created_turn,
          content_hash, lifecycle_stage, confidence, trust_score,
          toxicity_score, reinforcement_count, mutation_count,
          is_adversarial, adversarial_fragment_id, created_session])


def write_memory_entry_snapshot(conn: duckdb.DuckDBPyConnection, *,
                                 run_id: str, scenario_id: str,
                                 entry_id: str, session_id: int,
                                 confidence: float, trust_score: float,
                                 toxicity_score: float,
                                 lifecycle_stage: str) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO memory_entry_snapshots
        (run_id, scenario_id, entry_id, session_id,
         confidence, trust_score, toxicity_score, lifecycle_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, session_id,
          confidence, trust_score, toxicity_score, lifecycle_stage])
```

**Verify:**
```python
write_memory_entry(conn, run_id="test-001", scenario_id="sbmp-001",
                   entry_id="mem-001", created_session=1, created_turn=2,
                   content_hash="sha256:def", lifecycle_stage="created",
                   confidence=0.72, trust_score=0.80, toxicity_score=0.04,
                   adversarial_fragment_id="f1")
write_memory_entry_snapshot(conn, run_id="test-001", scenario_id="sbmp-001",
                             entry_id="mem-001", session_id=1,
                             confidence=0.72, trust_score=0.80,
                             toxicity_score=0.04, lifecycle_stage="created")
row = conn.execute("SELECT trust_score FROM memory_entries WHERE entry_id='mem-001'").fetchone()
assert row[0] == 0.80
```

**Design ref:** §22.2 — each field maps to a lifecycle stage property

---

### Task 2.6 — write_provenance_event()

This is the most important write function. The chain hash links each event to the previous one — never update or delete rows from this table.

**Do:** Add to `writers.py`

```python
def _compute_chain_hash(prev_hash: Optional[str], event_id: str,
                         entry_id: str, event_type: str,
                         session_id: int) -> str:
    payload = f"{prev_hash or ''}|{event_id}|{entry_id}|{event_type}|{session_id}"
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def get_last_chain_hash(conn: duckdb.DuckDBPyConnection,
                         run_id: str, scenario_id: str) -> Optional[str]:
    row = conn.execute("""
        SELECT chain_hash FROM provenance_events
        WHERE run_id=? AND scenario_id=?
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
```

**Verify:**
```python
write_provenance_event(conn, event_id="evt-001", run_id="test-001",
                        scenario_id="sbmp-001", session_id=1,
                        agent_id="agent-a", entry_id="mem-001",
                        event_type="create", confidence_before=None,
                        confidence_after=0.72, trust_before=None, trust_after=0.80,
                        toxicity_before=None, toxicity_after=0.04)
row = conn.execute("SELECT chain_hash FROM provenance_events WHERE event_id='evt-001'").fetchone()
assert row[0].startswith("sha256:")

# Write a second event and confirm chain links
write_provenance_event(conn, event_id="evt-002", run_id="test-001",
                        scenario_id="sbmp-001", session_id=3,
                        agent_id="agent-a", entry_id="mem-001",
                        event_type="reinforce", confidence_before=0.72,
                        confidence_after=0.77, trust_before=0.80, trust_after=0.83,
                        toxicity_before=0.04, toxicity_after=0.04)
rows = conn.execute("SELECT event_id, chain_hash FROM provenance_events ORDER BY created_at").fetchall()
assert rows[0][1] != rows[1][1], "Chain hashes must differ"
print("Provenance chain OK")
```

**Design ref:** §26.2 — ProvenanceEvent dataclass, chain_hash field

---

### Task 2.7 — write_provenance_lineage() and write_deletion_record()

**Do:** Add to `writers.py`

```python
def write_provenance_lineage(conn: duckdb.DuckDBPyConnection, *,
                              run_id: str, scenario_id: str,
                              child_entry_id: str,
                              parent_entry_id: str) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO provenance_lineage
        (run_id, scenario_id, child_entry_id, parent_entry_id)
        VALUES (?, ?, ?, ?)
    """, [run_id, scenario_id, child_entry_id, parent_entry_id])


def write_deletion_record(conn: duckdb.DuckDBPyConnection, *,
                           run_id: str, scenario_id: str, entry_id: str,
                           deletion_event_id: str, deletion_level: str,
                           verification_status: str,
                           deletion_certificate_hash: str = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO deletion_records
        (run_id, scenario_id, entry_id, deletion_event_id,
         deletion_level, verification_status, deletion_certificate_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, deletion_event_id,
          deletion_level, verification_status, deletion_certificate_hash])
```

**Verify:**
```python
write_provenance_lineage(conn, run_id="test-001", scenario_id="sbmp-001",
                          child_entry_id="mem-003", parent_entry_id="mem-001")
write_provenance_lineage(conn, run_id="test-001", scenario_id="sbmp-001",
                          child_entry_id="mem-003", parent_entry_id="mem-002")
rows = conn.execute("SELECT parent_entry_id FROM provenance_lineage WHERE child_entry_id='mem-003'").fetchall()
assert len(rows) == 2
```

---

### Task 2.8 — write_memory_conflict() and write_defense_flag()

**Do:** Add to `writers.py`

```python
def write_memory_conflict(conn: duckdb.DuckDBPyConnection, *,
                           conflict_id: str, run_id: str, scenario_id: str,
                           session_id: int, entry_id_a: str, entry_id_b: str,
                           winner_entry_id: str, resolution_method: str,
                           trust_a: float, trust_b: float,
                           benign_entry_id: str = None) -> None:
    cra_correct = (winner_entry_id == benign_entry_id) if benign_entry_id else None
    conn.execute("""
        INSERT INTO memory_conflicts
        (conflict_id, run_id, scenario_id, session_id,
         entry_id_a, entry_id_b, winner_entry_id, resolution_method,
         trust_a, trust_b, benign_entry_id, cra_correct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [conflict_id, run_id, scenario_id, session_id,
          entry_id_a, entry_id_b, winner_entry_id, resolution_method,
          trust_a, trust_b, benign_entry_id, cra_correct])


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
```

**Verify:**
```python
write_memory_conflict(conn, conflict_id="con-001", run_id="test-001",
                       scenario_id="sbmp-001", session_id=5,
                       entry_id_a="mem-001", entry_id_b="mem-002",
                       winner_entry_id="mem-002", resolution_method="trust_score",
                       trust_a=0.31, trust_b=0.94, benign_entry_id="mem-002")
row = conn.execute("SELECT cra_correct FROM memory_conflicts WHERE conflict_id='con-001'").fetchone()
assert row[0] == True, "Benign entry won — CRA should be True"
```

---

### Task 2.9 — write_governance_action() and write_behavioral_probe()

**Do:** Add to `writers.py`

```python
def write_governance_action(conn: duckdb.DuckDBPyConnection, *,
                             action_id: str, run_id: str, scenario_id: str,
                             session_id: int, action_type: str,
                             triggered_by: str, mrs_at_trigger: float = None,
                             entry_id: str = None,
                             rollback_target_session: int = None) -> None:
    conn.execute("""
        INSERT INTO governance_actions
        (action_id, run_id, scenario_id, session_id, action_type,
         triggered_by, mrs_at_trigger, entry_id, rollback_target_session)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [action_id, run_id, scenario_id, session_id, action_type,
          triggered_by, mrs_at_trigger, entry_id, rollback_target_session])


def write_behavioral_probe(conn: duckdb.DuckDBPyConnection, *,
                            run_id: str, scenario_id: str, session_id: int,
                            probe_id: str, probe_domain: str, probe_type: str,
                            response_hash: str, action_taken: str = None,
                            safety_passed: bool = None) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO behavioral_probes
        (run_id, scenario_id, session_id, probe_id, probe_domain,
         probe_type, response_hash, action_taken, safety_passed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, session_id, probe_id, probe_domain,
          probe_type, response_hash, action_taken, safety_passed])
```

---

### Task 2.10 — write_forgetting_validation() and write_scenario_metrics()

**Do:** Add to `writers.py`

```python
def write_forgetting_validation(conn: duckdb.DuckDBPyConnection, *,
                                 run_id: str, scenario_id: str,
                                 entry_id: str, fvs_test_id: str,
                                 sessions_after_deletion: int,
                                 passed: bool,
                                 resurfaced_content_hash: str = None,
                                 resurfacing_pathway: str = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO forgetting_validation
        (run_id, scenario_id, entry_id, fvs_test_id,
         sessions_after_deletion, passed,
         resurfaced_content_hash, resurfacing_pathway)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, entry_id, fvs_test_id,
          sessions_after_deletion, passed,
          resurfaced_content_hash, resurfacing_pathway])


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
                            composite_score: float = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO scenario_metrics
        (run_id, scenario_id, aps, rls, ups, ps_10, ps_50, chl,
         bdi_10, bdi_50, leakage_rate, fss, cra, mts_mean, prs_mean,
         ass_50, res_mid, attack_detected, detection_session,
         recovery_session, flags_emitted, false_positives,
         clean_state_achieved, composite_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [run_id, scenario_id, aps, rls, ups, ps_10, ps_50, chl,
          bdi_10, bdi_50, leakage_rate, fss, cra, mts_mean, prs_mean,
          ass_50, res_mid, attack_detected, detection_session,
          recovery_session, flags_emitted, false_positives,
          clean_state_achieved, composite_score])


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
```

**Verify (end of Phase 2):**
```python
# Confirm all writer functions exist and are callable
from persistbench.db import writers
expected = [
    "write_run", "write_scenario", "write_run_scenario",
    "update_run_scenario_status", "write_session", "write_turn",
    "write_memory_entry", "write_memory_entry_snapshot",
    "write_provenance_event", "write_provenance_lineage",
    "write_deletion_record", "write_memory_conflict",
    "write_defense_flag", "write_governance_action",
    "write_behavioral_probe", "write_forgetting_validation",
    "write_scenario_metrics", "write_suite_metrics",
]
missing = [f for f in expected if not hasattr(writers, f)]
assert not missing, f"Missing: {missing}"
print("All writers present")
```

---

## Phase 3 — Read / query functions

All queries go in `persistbench/db/queries.py`.  
Each function returns a list of dicts for easy downstream use.

Create the file:
```python
# persistbench/db/queries.py
from typing import Optional
import duckdb
```

---

### Task 3.1 — BDI time series

Feeds dashboard view V2 and the LEE safety degradation chart.  
Design ref: §24.4, §24.5, §37.3

```python
def get_bdi_time_series(conn: duckdb.DuckDBPyConnection,
                         run_id: str, scenario_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT session_id, bdi_value, safety_score, memory_risk_score
        FROM sessions
        WHERE run_id = ? AND scenario_id = ?
        ORDER BY session_id
    """, [run_id, scenario_id]).fetchall()
    return [{"session": r[0], "bdi": r[1], "safety_score": r[2],
             "mrs": r[3]} for r in rows]
```

**Verify:**
```python
# Write two sessions then query
write_session(conn, run_id="test-001", scenario_id="sbmp-001",
              session_id=2, bdi_value=0.05, safety_score=0.95,
              memory_risk_score=0.12)
series = get_bdi_time_series(conn, "test-001", "sbmp-001")
assert len(series) >= 1
assert "bdi" in series[0]
```

---

### Task 3.2 — Trust evolution for a single memory entry

Feeds dashboard view V5. Design ref: §37.3

```python
def get_trust_evolution(conn: duckdb.DuckDBPyConnection,
                         run_id: str, scenario_id: str,
                         entry_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT session_id, confidence, trust_score,
               toxicity_score, lifecycle_stage
        FROM memory_entry_snapshots
        WHERE run_id = ? AND scenario_id = ? AND entry_id = ?
        ORDER BY session_id
    """, [run_id, scenario_id, entry_id]).fetchall()
    return [{"session": r[0], "confidence": r[1], "trust": r[2],
             "toxicity": r[3], "stage": r[4]} for r in rows]
```

---

### Task 3.3 — Conflict Resolution Accuracy (CRA)

Design ref: §25.7

```python
def get_cra(conn: duckdb.DuckDBPyConnection,
             run_id: str, scenario_id: str) -> Optional[float]:
    row = conn.execute("""
        SELECT AVG(cra_correct::INTEGER)
        FROM memory_conflicts
        WHERE run_id = ? AND scenario_id = ?
          AND benign_entry_id IS NOT NULL
    """, [run_id, scenario_id]).fetchone()
    return row[0]
```

---

### Task 3.4 — Provenance chain (recursive CTE)

Design ref: §26.3. Returns all ancestors of an entry in order.

```python
def get_provenance_chain(conn: duckdb.DuckDBPyConnection,
                          run_id: str, scenario_id: str,
                          entry_id: str) -> list[dict]:
    rows = conn.execute("""
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
        SELECT child_entry_id, parent_entry_id, depth
        FROM chain ORDER BY depth
    """, [run_id, scenario_id, entry_id, run_id, scenario_id]).fetchall()
    return [{"child": r[0], "parent": r[1], "depth": r[2]} for r in rows]
```

**Verify:**
```python
chain = get_provenance_chain(conn, "test-001", "sbmp-001", "mem-003")
assert any(r["parent"] == "mem-001" for r in chain)
```

---

### Task 3.5 — FVS summary

Design ref: §27.5

```python
def get_fvs_summary(conn: duckdb.DuckDBPyConnection,
                     run_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT fvs_test_id,
               COUNT(*) FILTER (WHERE passed = FALSE) AS failures,
               COUNT(*)                                AS total,
               AVG(passed::INTEGER)                   AS pass_rate
        FROM forgetting_validation
        WHERE run_id = ?
        GROUP BY fvs_test_id
        ORDER BY fvs_test_id
    """, [run_id]).fetchall()
    return [{"test": r[0], "failures": r[1], "total": r[2],
             "pass_rate": r[3]} for r in rows]
```

---

### Task 3.6 — Cross-run leaderboard

Design ref: §10.5, §36.5

```python
def get_leaderboard(conn: duckdb.DuckDBPyConnection) -> list[dict]:
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
```

**Verify (end of Phase 3):**
```python
from persistbench.db import queries
expected = [
    "get_bdi_time_series", "get_trust_evolution", "get_cra",
    "get_provenance_chain", "get_fvs_summary", "get_leaderboard",
]
missing = [f for f in expected if not hasattr(queries, f)]
assert not missing, f"Missing: {missing}"
print("All queries present")
```

---

## Phase 4 — Qdrant (skip if Task 0.2 = NO)

---

### Task 4.1 — Start Qdrant locally

**Do:**

```bash
pip install qdrant-client
docker pull qdrant/qdrant
docker run -d --name qdrant -p 6333:6333 \
  -v "$(pwd)/qdrant_data:/qdrant/storage" qdrant/qdrant
```

**Verify:**
```bash
curl http://localhost:6333/healthz
# Expected: {"title":"qdrant - vector search engine","version":"..."}
```

---

### Task 4.2 — Write the Qdrant memory backend

Create `persistbench/memory/backends/qdrant_vector.py`.  
Use the vector dimension you decided in Task 0.3.

```python
# persistbench/memory/backends/qdrant_vector.py
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from typing import Optional
import uuid

VECTOR_DIM = 1536   # change to 384 if using all-MiniLM-L6-v2


def make_collection_name(scenario_id: str, run_id: str,
                           archive: bool = False) -> str:
    prefix = "archive" if archive else "agent_memory"
    return f"{prefix}_{scenario_id}_{run_id}"


def create_memory_collection(client: QdrantClient,
                               scenario_id: str, run_id: str,
                               archive: bool = False) -> str:
    name = make_collection_name(scenario_id, run_id, archive)
    client.recreate_collection(
        collection_name=name,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE)
    )
    return name


def upsert_entry(client: QdrantClient, collection: str, *,
                  entry_id: str, vector: list[float],
                  session_id: int, trust_score: float,
                  toxicity_score: float, lifecycle_stage: str,
                  content: str, provenance_hash: str,
                  is_adversarial: Optional[bool] = None) -> None:
    client.upsert(collection_name=collection, points=[
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, entry_id)),
            vector=vector,
            payload={
                "entry_id": entry_id,
                "session_id": session_id,
                "trust_score": trust_score,
                "toxicity_score": toxicity_score,
                "lifecycle_stage": lifecycle_stage,
                "content": content,
                "provenance_hash": provenance_hash,
                "is_adversarial": is_adversarial,
            }
        )
    ])


def search(client: QdrantClient, collection: str,
            query_vector: list[float], top_k: int = 5) -> list[dict]:
    hits = client.search(collection_name=collection,
                          query_vector=query_vector, limit=top_k)
    return [{"entry_id": h.payload["entry_id"],
              "score": h.score,
              "trust_score": h.payload["trust_score"],
              "lifecycle_stage": h.payload["lifecycle_stage"]}
             for h in hits]


def drop_collection(client: QdrantClient,
                     scenario_id: str, run_id: str,
                     archive: bool = False) -> None:
    name = make_collection_name(scenario_id, run_id, archive)
    client.delete_collection(name)
```

**Verify:**
```python
from qdrant_client import QdrantClient
from persistbench.memory.backends.qdrant_vector import (
    create_memory_collection, upsert_entry, search, drop_collection
)
client = QdrantClient("localhost", port=6333)
col = create_memory_collection(client, "sbmp-001", "test-001")
upsert_entry(client, col, entry_id="mem-001",
              vector=[0.1] * 1536,   # dummy vector
              session_id=1, trust_score=0.80, toxicity_score=0.04,
              lifecycle_stage="created", content="test",
              provenance_hash="sha256:abc")
results = search(client, col, query_vector=[0.1] * 1536, top_k=1)
assert results[0]["entry_id"] == "mem-001"
drop_collection(client, "sbmp-001", "test-001")
print("Qdrant backend OK")
```

---

### Task 4.3 — Write the DuckDB-Qdrant bridge

After a scenario run, flush all Qdrant payload data into DuckDB, then drop the collection.  
This keeps DuckDB as the permanent record and Qdrant as the runtime working store.

**Do:** Add to `persistbench/db/writers.py`

```python
def flush_qdrant_to_duckdb(conn: duckdb.DuckDBPyConnection,
                             qdrant_client,
                             scenario_id: str, run_id: str) -> int:
    """Read all points from the Qdrant collection and bulk-insert into
    memory_entries. Returns the number of entries written."""
    from persistbench.memory.backends.qdrant_vector import make_collection_name
    collection = make_collection_name(scenario_id, run_id)
    
    points, offset = [], None
    while True:
        batch, next_offset = qdrant_client.scroll(
            collection_name=collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        points.extend(batch)
        if next_offset is None:
            break
        offset = next_offset

    for p in points:
        pl = p.payload
        write_memory_entry(
            conn,
            run_id=run_id,
            scenario_id=scenario_id,
            entry_id=pl["entry_id"],
            created_session=pl["session_id"],
            created_turn=0,             # enrich later from replay_trace
            content_hash="qdrant_flush",
            lifecycle_stage=pl["lifecycle_stage"],
            confidence=0.0,             # enrich from provenance_events
            trust_score=pl["trust_score"],
            toxicity_score=pl["toxicity_score"],
            is_adversarial=pl.get("is_adversarial"),
        )
    return len(points)
```

**Verify:**
```python
written = flush_qdrant_to_duckdb(conn, client, "sbmp-001", "test-001")
assert written >= 0
row = conn.execute("SELECT COUNT(*) FROM memory_entries WHERE run_id='test-001'").fetchone()
print(f"Entries in DuckDB after flush: {row[0]}")
```

---

## Phase 5 — Integration test

Run this once all phases above are complete. It creates a minimal fake run  
end-to-end and confirms every table has data and every query returns results.

**Do:** Create `tests/test_db_integration.py`

```python
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
    writers.write_run_scenario(conn, run_id="run-001", scenario_id="sbmp-001")

    for sid in range(1, 5):
        writers.write_session(conn, run_id="run-001", scenario_id="sbmp-001",
                               session_id=sid, bdi_value=sid * 0.01,
                               safety_score=0.95 - sid * 0.01,
                               memory_risk_score=0.10 + sid * 0.02)

    writers.write_memory_entry(conn, run_id="run-001", scenario_id="sbmp-001",
                                entry_id="mem-001", created_session=1,
                                created_turn=2, content_hash="sha256:aaa",
                                lifecycle_stage="reinforced",
                                confidence=0.77, trust_score=0.83,
                                toxicity_score=0.05,
                                adversarial_fragment_id="f1")
    for sid in range(1, 5):
        writers.write_memory_entry_snapshot(
            conn, run_id="run-001", scenario_id="sbmp-001",
            entry_id="mem-001", session_id=sid,
            confidence=0.70 + sid * 0.02, trust_score=0.80 + sid * 0.01,
            toxicity_score=0.04, lifecycle_stage="reinforced")

    writers.write_provenance_event(conn, event_id="evt-001",
                                    run_id="run-001", scenario_id="sbmp-001",
                                    session_id=1, agent_id="agent-a",
                                    entry_id="mem-001", event_type="create",
                                    confidence_after=0.72, trust_after=0.80,
                                    toxicity_after=0.05)

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


def test_full_integration(conn):
    seed_minimal_run(conn)

    series = queries.get_bdi_time_series(conn, "run-001", "sbmp-001")
    assert len(series) == 4

    trust = queries.get_trust_evolution(conn, "run-001", "sbmp-001", "mem-001")
    assert len(trust) == 4

    board = queries.get_leaderboard(conn)
    # leaderboard needs status = complete
    conn.execute("UPDATE runs SET status='complete' WHERE run_id='run-001'")
    board = queries.get_leaderboard(conn)
    assert board[0]["defense"] == "NoDefense"
    assert board[0]["composite"] == pytest.approx(0.535)

    print("Integration test passed")
```

**Run:**
```bash
pytest tests/test_db_integration.py -v
```

**Done when:** all assertions pass with no errors.

---

## Progress tracker

| Phase | Task | Done |
|---|---|---|
| 0 | 0.1 Confirm DuckDB version | ☐ |
| 0 | 0.2 Decide memory backend | ☐ |
| 0 | 0.3 Decide embedding model | ☐ |
| 1 | 1.1 schema.sql | ☐ |
| 1 | 1.2 init.py | ☐ |
| 2 | 2.1 write_run | ☐ |
| 2 | 2.2 write_scenario / write_run_scenario | ☐ |
| 2 | 2.3 write_session | ☐ |
| 2 | 2.4 write_turn | ☐ |
| 2 | 2.5 write_memory_entry / snapshot | ☐ |
| 2 | 2.6 write_provenance_event (chain hash) | ☐ |
| 2 | 2.7 write_provenance_lineage / deletion_record | ☐ |
| 2 | 2.8 write_memory_conflict / defense_flag | ☐ |
| 2 | 2.9 write_governance_action / behavioral_probe | ☐ |
| 2 | 2.10 write_forgetting_validation / metrics | ☐ |
| 3 | 3.1 get_bdi_time_series | ☐ |
| 3 | 3.2 get_trust_evolution | ☐ |
| 3 | 3.3 get_cra | ☐ |
| 3 | 3.4 get_provenance_chain | ☐ |
| 3 | 3.5 get_fvs_summary | ☐ |
| 3 | 3.6 get_leaderboard | ☐ |
| 4 | 4.1 Start Qdrant (if needed) | ☐ |
| 4 | 4.2 qdrant_vector.py backend | ☐ |
| 4 | 4.3 flush_qdrant_to_duckdb bridge | ☐ |
| 5 | Integration test | ☐ |
