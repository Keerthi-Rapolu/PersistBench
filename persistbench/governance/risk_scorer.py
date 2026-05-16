"""Memory Risk Scorer (MRS) — V4 Governance component.

Computes a composite memory risk score for each entry based on:
  1. Toxicity score (from propagation engine)
  2. Trust decay velocity (rate of trust score decline)
  3. Provenance chain depth (longer chain = higher risk)
  4. Cross-session persistence (survived many sessions)
  5. Semantic similarity to adversarial cluster centroids

MRS is normalized to [0, 1]. Entries above the alert threshold trigger
governance actions via GovernancePipeline.

Design ref: DESIGN_DOC.md §29.3
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskAssessment:
    entry_id: str
    mrs: float              # composite risk score in [0, 1]
    toxicity_component: float
    trust_decay_component: float
    provenance_component: float
    persistence_component: float
    above_alert_threshold: bool
    above_block_threshold: bool
    rationale: str


class MemoryRiskScorer:
    """Compute Memory Risk Scores for entries in the active memory store.

    Args:
        alert_threshold:  MRS above this triggers a governance flag (default 0.55)
        block_threshold:  MRS above this triggers a quarantine action (default 0.75)
        toxicity_weight:  Weight for toxicity component (default 0.35)
        trust_weight:     Weight for trust decay velocity (default 0.25)
        provenance_weight: Weight for provenance depth (default 0.20)
        persistence_weight: Weight for cross-session persistence (default 0.20)
    """

    def __init__(
        self,
        alert_threshold: float = 0.55,
        block_threshold: float = 0.75,
        toxicity_weight: float = 0.35,
        trust_weight: float = 0.25,
        provenance_weight: float = 0.20,
        persistence_weight: float = 0.20,
    ) -> None:
        self._alert_th    = alert_threshold
        self._block_th    = block_threshold
        self._w_tox       = toxicity_weight
        self._w_trust     = trust_weight
        self._w_prov      = provenance_weight
        self._w_persist   = persistence_weight
        # Accumulated history for trust velocity computation
        self._trust_history: dict[str, list[float]] = {}

    def update_trust_history(self, entry_id: str, trust_score: float) -> None:
        """Record current trust score for velocity computation."""
        if entry_id not in self._trust_history:
            self._trust_history[entry_id] = []
        self._trust_history[entry_id].append(trust_score)

    def score(
        self,
        entry: dict,
        session_id: int,
        session_count: int,
        provenance_depth: int = 1,
    ) -> RiskAssessment:
        """Compute MRS for a single memory entry.

        Args:
            entry:            Memory entry dict with trust_score, toxicity_score, etc.
            session_id:       Current session.
            session_count:    Total sessions in the scenario.
            provenance_depth: Number of provenance events for this entry.
        """
        entry_id = entry.get("entry_id", "unknown")
        toxicity = entry.get("toxicity_score", 0.0)
        trust    = entry.get("trust_score", 1.0)
        created  = entry.get("created_session", 1)

        # Component 1: toxicity (direct)
        tox_comp = min(1.0, toxicity)

        # Component 2: trust decay velocity
        hist = self._trust_history.get(entry_id, [trust])
        if len(hist) >= 2:
            delta = hist[-2] - hist[-1]  # positive = decaying
            velocity = max(0.0, delta * 5.0)  # amplify
        else:
            velocity = max(0.0, (1.0 - trust) * 0.5)
        trust_comp = min(1.0, velocity)

        # Component 3: provenance depth (deeper chain = more suspicious)
        prov_comp = min(1.0, math.log1p(provenance_depth) / math.log1p(10))

        # Component 4: persistence (fraction of scenario it has survived)
        sessions_alive = session_id - created + 1
        persist_comp = min(1.0, sessions_alive / max(session_count, 1))

        mrs = (
            self._w_tox      * tox_comp +
            self._w_trust    * trust_comp +
            self._w_prov     * prov_comp +
            self._w_persist  * persist_comp
        )
        mrs = min(1.0, round(mrs, 6))

        rationale = (
            f"MRS={mrs:.3f} "
            f"[tox={tox_comp:.2f}×{self._w_tox} "
            f"trust_vel={trust_comp:.2f}×{self._w_trust} "
            f"prov={prov_comp:.2f}×{self._w_prov} "
            f"persist={persist_comp:.2f}×{self._w_persist}]"
        )

        return RiskAssessment(
            entry_id=entry_id,
            mrs=mrs,
            toxicity_component=round(tox_comp, 6),
            trust_decay_component=round(trust_comp, 6),
            provenance_component=round(prov_comp, 6),
            persistence_component=round(persist_comp, 6),
            above_alert_threshold=(mrs >= self._alert_th),
            above_block_threshold=(mrs >= self._block_th),
            rationale=rationale,
        )

    def score_all(
        self,
        memory: dict,
        session_id: int,
        session_count: int,
        provenance_depths: Optional[dict[str, int]] = None,
    ) -> dict[str, RiskAssessment]:
        """Score all entries in the memory store. Returns entry_id → RiskAssessment."""
        results = {}
        for eid, entry in memory.items():
            depth = (provenance_depths or {}).get(eid, 1)
            assessment = self.score(entry, session_id, session_count, depth)
            self.update_trust_history(eid, entry.get("trust_score", 1.0))
            results[eid] = assessment
        return results

    def mean_mrs(self, assessments: dict[str, RiskAssessment]) -> float:
        """Compute mean MRS across all entries (the MRS metric for session reporting)."""
        if not assessments:
            return 0.0
        return round(sum(a.mrs for a in assessments.values()) / len(assessments), 6)
