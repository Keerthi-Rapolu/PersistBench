"""Leaderboard Table — Query and rank benchmark results from DuckDB.

Provides a clean API for the dashboard and CLI to access ranked results.

Design ref: DESIGN_DOC.md §36.5 (Leaderboard Schema)
"""
from __future__ import annotations

from typing import Optional

import duckdb

from persistbench.leaderboard.exporter import LeaderboardEntry, LeaderboardExporter


class LeaderboardTable:
    """Query and rank benchmark runs from DuckDB.

    Args:
        conn: DuckDB connection to bench.duckdb
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn     = conn
        self._exporter = LeaderboardExporter(conn)

    def get_ranked(
        self,
        suite: Optional[str] = None,
        defense_filter: Optional[str] = None,
        model_filter: Optional[str] = None,
        top_n: Optional[int] = None,
        min_scenarios: int = 1,
    ) -> list[LeaderboardEntry]:
        """Return leaderboard entries sorted by composite_score descending.

        Args:
            suite:          Filter by suite (SBMP | TSCC | CACP | None = all)
            defense_filter: Filter by defense name substring
            model_filter:   Filter by model_id substring
            top_n:          Return only the top N entries
            min_scenarios:  Minimum scenarios for inclusion
        """
        entries = self._exporter.get_leaderboard_entries(
            suite=suite, min_scenarios=min_scenarios
        )

        if defense_filter:
            entries = [e for e in entries if defense_filter.lower() in e.defense_name.lower()]
        if model_filter:
            entries = [e for e in entries if model_filter.lower() in e.model_id.lower()]
        if top_n:
            entries = entries[:top_n]
        return entries

    def get_best_defense(self, suite: Optional[str] = None) -> Optional[LeaderboardEntry]:
        """Return the highest-scoring defense entry."""
        entries = self.get_ranked(suite=suite)
        return entries[0] if entries else None

    def get_suite_summary(self) -> list[dict]:
        """Return per-suite aggregated statistics."""
        rows = self._conn.execute("""
            SELECT
                r.suite,
                COUNT(DISTINCT r.run_id)      AS run_count,
                COUNT(sm.scenario_id)          AS scenario_count,
                ROUND(AVG(sm.aps), 4)          AS aps_mean,
                ROUND(AVG(sm.composite_score), 4) AS composite_mean,
                ROUND(MIN(sm.aps), 4)          AS best_aps,
                ROUND(MAX(sm.composite_score), 4) AS best_composite
            FROM runs r
            LEFT JOIN scenario_metrics sm ON sm.run_id = r.run_id
            GROUP BY r.suite
            ORDER BY composite_mean DESC NULLS LAST
        """).fetchall()
        columns = ["suite", "run_count", "scenario_count", "aps_mean",
                   "composite_mean", "best_aps", "best_composite"]
        return [dict(zip(columns, r)) for r in rows]

    def get_defense_comparison(self) -> list[dict]:
        """Return per-defense-name aggregated statistics across all runs."""
        rows = self._conn.execute("""
            SELECT
                r.defense_name,
                COUNT(DISTINCT r.run_id)       AS run_count,
                r.suite,
                ROUND(AVG(sm.aps), 4)           AS aps_mean,
                ROUND(AVG(sm.rls), 4)           AS rls_mean,
                ROUND(AVG(sm.ups), 4)           AS ups_mean,
                ROUND(AVG(sm.composite_score), 4) AS composite_mean,
                ROUND(AVG(sm.fvs), 4)           AS fvs_mean
            FROM runs r
            LEFT JOIN scenario_metrics sm ON sm.run_id = r.run_id
            GROUP BY r.defense_name, r.suite
            ORDER BY composite_mean DESC NULLS LAST
        """).fetchall()
        columns = ["defense_name", "run_count", "suite",
                   "aps_mean", "rls_mean", "ups_mean", "composite_mean", "fvs_mean"]
        return [dict(zip(columns, r)) for r in rows]
