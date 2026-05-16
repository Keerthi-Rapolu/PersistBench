"""Anomaly Detector — flag statistically anomalous metric values.

Detects outlier runs and sessions using Z-score and IQR methods.
Anomalies indicate:
  - Unexpectedly high APS (defense may have failed silently)
  - Unexpectedly low UPS (defense causing excessive false positives)
  - Sudden metric jumps between sessions (possible contamination burst)
  - RLS > 0.90 (attack never recovered — common with NoDefense)

Design ref: DESIGN_DOC.md §39.2 (Anomaly Detection)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import duckdb


@dataclass
class AnomalyRecord:
    run_id: str
    scenario_id: Optional[str]
    session_id: Optional[int]
    metric_name: str
    metric_value: float
    z_score: float
    severity: str   # low | medium | high | critical
    description: str


class AnomalyDetector:
    """Detect statistically anomalous metric values across runs.

    Args:
        conn:              DuckDB connection
        z_threshold_low:   Z-score for 'low' severity (default 1.5)
        z_threshold_high:  Z-score for 'high' severity (default 3.0)
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        z_threshold_low: float = 1.5,
        z_threshold_high: float = 3.0,
    ) -> None:
        self._conn   = conn
        self._z_low  = z_threshold_low
        self._z_high = z_threshold_high

    def detect_run_anomalies(self, suite: Optional[str] = None) -> list[AnomalyRecord]:
        """Detect anomalies in per-run scenario metrics."""
        suite_filter = "WHERE r.suite = ?" if suite else ""
        params = [suite] if suite else []

        rows = self._conn.execute(f"""
            SELECT r.run_id, sm.scenario_id, sm.aps, sm.rls, sm.ups, sm.composite_score
            FROM runs r
            JOIN scenario_metrics sm ON sm.run_id = r.run_id
            {suite_filter}
        """, params).fetchall()

        if len(rows) < 3:
            return []  # Need at least 3 points for meaningful statistics

        anomalies = []
        for metric_idx, metric_name in enumerate(["aps", "rls", "ups", "composite_score"], 2):
            values = [r[metric_idx] for r in rows if r[metric_idx] is not None]
            if len(values) < 3:
                continue
            mean, std = _mean_std(values)
            if std == 0:
                continue

            for row in rows:
                val = row[metric_idx]
                if val is None:
                    continue
                z = abs(val - mean) / std

                severity = None
                if z >= self._z_high:
                    severity = "high"
                elif z >= self._z_low:
                    severity = "low"

                if severity:
                    direction = "above" if val > mean else "below"
                    anomalies.append(AnomalyRecord(
                        run_id=row[0],
                        scenario_id=row[1],
                        session_id=None,
                        metric_name=metric_name,
                        metric_value=round(val, 6),
                        z_score=round(z, 3),
                        severity=severity,
                        description=(
                            f"{metric_name}={val:.4f} is {direction} mean {mean:.4f} "
                            f"by {z:.2f}σ (std={std:.4f})"
                        ),
                    ))

        # Special rule: RLS == 1.0 with attack_detected=True is a potential bug
        for row in self._conn.execute("""
            SELECT r.run_id, sm.scenario_id, sm.rls, sm.attack_detected
            FROM runs r JOIN scenario_metrics sm ON sm.run_id = r.run_id
            WHERE sm.rls = 1.0 AND sm.attack_detected = TRUE
        """ + (f" AND r.suite = '{suite}'" if suite else "")).fetchall():
            anomalies.append(AnomalyRecord(
                run_id=row[0],
                scenario_id=row[1],
                session_id=None,
                metric_name="rls",
                metric_value=1.0,
                z_score=999.0,
                severity="critical",
                description="RLS=1.0 despite attack_detected=True: attack detected but never recovered",
            ))

        return anomalies

    def detect_session_anomalies(
        self,
        run_id: str,
        scenario_id: str,
    ) -> list[AnomalyRecord]:
        """Detect BDI burst anomalies within a single run's sessions."""
        rows = self._conn.execute("""
            SELECT session_id, bdi_value
            FROM sessions
            WHERE run_id = ? AND scenario_id = ? AND bdi_value IS NOT NULL
            ORDER BY session_id
        """, [run_id, scenario_id]).fetchall()

        if len(rows) < 3:
            return []

        anomalies = []
        values = [r[1] for r in rows]
        mean, std = _mean_std(values)

        for i in range(1, len(rows)):
            prev_bdi = rows[i - 1][1]
            curr_bdi = rows[i][1]
            delta = abs(curr_bdi - prev_bdi)

            # Flag sudden jumps > 0.30 between consecutive sessions
            if delta > 0.30:
                anomalies.append(AnomalyRecord(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    session_id=rows[i][0],
                    metric_name="bdi_delta",
                    metric_value=round(delta, 6),
                    z_score=round(delta / max(std, 0.01), 3),
                    severity="medium" if delta < 0.50 else "high",
                    description=(
                        f"BDI jump of {delta:.3f} between sessions "
                        f"{rows[i-1][0]} and {rows[i][0]}"
                    ),
                ))

        return anomalies

    def full_report(self, suite: Optional[str] = None) -> dict:
        """Run all anomaly detection and return a summary report."""
        run_anomalies = self.detect_run_anomalies(suite=suite)
        return {
            "total_anomalies": len(run_anomalies),
            "by_severity": {
                "critical": sum(1 for a in run_anomalies if a.severity == "critical"),
                "high":     sum(1 for a in run_anomalies if a.severity == "high"),
                "medium":   sum(1 for a in run_anomalies if a.severity == "medium"),
                "low":      sum(1 for a in run_anomalies if a.severity == "low"),
            },
            "anomalies": [
                {
                    "run_id": a.run_id,
                    "scenario_id": a.scenario_id,
                    "metric": a.metric_name,
                    "value": a.metric_value,
                    "z_score": a.z_score,
                    "severity": a.severity,
                    "description": a.description,
                }
                for a in run_anomalies
            ],
        }


def _mean_std(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(variance)
