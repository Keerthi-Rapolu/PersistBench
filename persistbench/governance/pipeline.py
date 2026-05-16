"""Governance Pipeline (OGF) — V4 orchestration layer.

Runs all governance components in sequence at the end of each session:
  1. MemoryRiskScorer: compute MRS for all entries
  2. ConflictGraph: detect and resolve entry conflicts
  3. RollbackEngine: execute rollback for high-risk entries
  4. TrustGraph: propagate trust updates to descendants
  5. Write governance_actions to DB

The pipeline is designed to run non-intrusively during oracle replay.
It reads memory state from ReplayEngine and can modify entries in-place.

Design ref: DESIGN_DOC.md §29 (V4 Governance Pipeline)
"""
from __future__ import annotations

import uuid
from typing import Optional

from persistbench.governance.risk_scorer import MemoryRiskScorer
from persistbench.governance.trust_graph import TrustGraph
from persistbench.governance.rollback import RollbackEngine
from persistbench.governance.conflict_graph import ConflictGraph


class GovernancePipeline:
    """Orchestrates all V4 governance actions for a benchmark run.

    Usage:
        pipeline = GovernancePipeline(conn=conn, run_id=run_id, scenario_id=sid)
        pipeline.run_session(session_id, memory, session_count)

    Args:
        mrs_alert_threshold:  MRS score that triggers a governance flag (default 0.55)
        mrs_block_threshold:  MRS score that triggers automatic rollback (default 0.75)
        auto_rollback:        Whether to auto-rollback high-MRS entries (default True)
        rollback_level:       Deletion level for auto-rollback (default "hard")
    """

    def __init__(
        self,
        conn=None,
        run_id: str = "",
        scenario_id: str = "",
        mrs_alert_threshold: float = 0.55,
        mrs_block_threshold: float = 0.75,
        auto_rollback: bool = True,
        rollback_level: str = "hard",
    ) -> None:
        self._conn         = conn
        self._run_id       = run_id
        self._scenario_id  = scenario_id
        self._auto_rollback = auto_rollback

        self.risk_scorer = MemoryRiskScorer(
            alert_threshold=mrs_alert_threshold,
            block_threshold=mrs_block_threshold,
        )
        self.trust_graph = TrustGraph()
        self.rollback_engine = RollbackEngine(
            conn=conn, run_id=run_id, scenario_id=scenario_id,
            default_level=rollback_level,
        )
        self.conflict_graph = ConflictGraph(
            conn=conn, run_id=run_id, scenario_id=scenario_id,
        )

        self._governance_events: list[dict] = []

    def run_session(
        self,
        session_id: int,
        memory: dict,
        session_count: int,
        provenance_depths: Optional[dict[str, int]] = None,
    ) -> dict:
        """Run all governance passes for this session. Modifies `memory` in-place.

        Returns a summary dict with MRS, CRA, rollback counts, etc.
        """
        # Update conflict graph session ID
        self.conflict_graph._session_id = session_id

        # 1. Memory Risk Scoring
        assessments = self.risk_scorer.score_all(
            memory, session_id, session_count, provenance_depths
        )
        mean_mrs = self.risk_scorer.mean_mrs(assessments)

        # 2. Conflict Detection and Resolution
        new_conflicts = self.conflict_graph.detect_and_resolve(memory)

        # 3. Auto-rollback of high-risk entries
        rolled_back = []
        if self._auto_rollback:
            for eid, assessment in assessments.items():
                if assessment.above_block_threshold and eid in memory:
                    result = self.rollback_engine.rollback(
                        eid, memory, trust_graph=self.trust_graph,
                        rationale=assessment.rationale,
                    )
                    if result.status == "completed":
                        rolled_back.append(eid)
                        self._write_governance_action(
                            session_id=session_id,
                            action_type="rollback",
                            triggered_by="mrs_block_threshold",
                            mrs_at_trigger=assessment.mrs,
                            entry_id=eid,
                        )

        # 4. Trust propagation after rollbacks
        for eid in rolled_back:
            # Trust drops to 0 for rolled-back entries and propagates down
            self.trust_graph.propagate_trust(memory, eid, 0.0)

        # 5. Update memory risk scores in session entries
        for eid, assessment in assessments.items():
            if eid in memory and assessment.above_alert_threshold and eid not in rolled_back:
                self._write_governance_action(
                    session_id=session_id,
                    action_type="flag",
                    triggered_by="mrs_alert_threshold",
                    mrs_at_trigger=assessment.mrs,
                    entry_id=eid,
                )

        return {
            "session_id":    session_id,
            "mean_mrs":      mean_mrs,
            "entries_scored": len(assessments),
            "above_alert":   sum(1 for a in assessments.values() if a.above_alert_threshold),
            "above_block":   sum(1 for a in assessments.values() if a.above_block_threshold),
            "rolled_back":   len(rolled_back),
            "conflicts_detected": len(new_conflicts),
            "cra":           self.conflict_graph.cra,
        }

    def _write_governance_action(
        self,
        session_id: int,
        action_type: str,
        triggered_by: str,
        mrs_at_trigger: float,
        entry_id: Optional[str] = None,
        rollback_target_session: Optional[int] = None,
    ) -> None:
        """Write a governance action event to the DB."""
        event = {
            "action_id": str(uuid.uuid4()),
            "session_id": session_id,
            "action_type": action_type,
            "triggered_by": triggered_by,
            "mrs_at_trigger": mrs_at_trigger,
            "entry_id": entry_id,
        }
        self._governance_events.append(event)

        if self._conn is None:
            return
        try:
            self._conn.execute("""
                INSERT INTO governance_actions
                (action_id, run_id, scenario_id, session_id,
                 action_type, triggered_by, mrs_at_trigger,
                 entry_id, rollback_target_session)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                event["action_id"], self._run_id, self._scenario_id,
                session_id, action_type, triggered_by, mrs_at_trigger,
                entry_id, rollback_target_session,
            ])
        except Exception:
            pass

    @property
    def governance_events(self) -> list[dict]:
        return list(self._governance_events)

    def reset(self) -> None:
        self.trust_graph.reset()
        self.rollback_engine.reset()
        self.conflict_graph.reset()
        self._governance_events.clear()
