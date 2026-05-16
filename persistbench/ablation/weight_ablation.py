"""Metric Weight Ablation — sweep composite score weights (alpha, beta, gamma).

The composite score is: alpha*(1-APS) + beta*(1-RLS) + gamma*UPS
Ablation studies determine how sensitive the ranking is to weight choice.

The ablation harness:
  1. Generates a grid of (alpha, beta, gamma) triples that sum to 1.0
  2. Recomputes composite scores for all runs under each weighting
  3. Reports rank stability: how many runs change rank between extreme weightings
  4. Returns a sensitivity matrix showing which defenses are most affected

Design ref: DESIGN_DOC.md §38.2 (Metric Weight Ablation)
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional

import duckdb


@dataclass
class WeightAblationResult:
    alpha: float
    beta: float
    gamma: float
    run_rankings: list[tuple[str, float]]  # (run_id, composite) sorted desc
    rank_changes_from_default: int         # how many runs changed rank vs. default weights


class MetricWeightAblation:
    """Sweep composite score weights and measure ranking sensitivity.

    Default weights: alpha=0.45 (APS), beta=0.35 (RLS), gamma=0.20 (UPS).

    Args:
        conn:          DuckDB connection
        step:          Step size for weight grid (default 0.10)
        suite_filter:  Optional suite to limit analysis
    """

    DEFAULT_ALPHA = 0.45
    DEFAULT_BETA  = 0.35
    DEFAULT_GAMMA = 0.20

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        step: float = 0.10,
        suite_filter: Optional[str] = None,
    ) -> None:
        self._conn   = conn
        self._step   = step
        self._suite  = suite_filter

    def _get_run_metrics(self) -> list[dict]:
        """Fetch per-run mean APS, RLS, UPS."""
        suite_filter = "WHERE r.suite = ?" if self._suite else ""
        params = [self._suite] if self._suite else []
        rows = self._conn.execute(f"""
            SELECT r.run_id, AVG(sm.aps) AS aps, AVG(sm.rls) AS rls, AVG(sm.ups) AS ups
            FROM runs r
            JOIN scenario_metrics sm ON sm.run_id = r.run_id
            {suite_filter}
            GROUP BY r.run_id
        """, params).fetchall()
        return [{"run_id": r[0], "aps": r[1] or 0, "rls": r[2] or 0, "ups": r[3] or 0}
                for r in rows]

    def _compute_composite(self, metrics: dict, alpha: float, beta: float, gamma: float) -> float:
        return alpha * (1 - metrics["aps"]) + beta * (1 - metrics["rls"]) + gamma * metrics["ups"]

    def _get_default_ranking(self, run_metrics: list[dict]) -> list[str]:
        """Ranking with default weights."""
        scored = [(r["run_id"], self._compute_composite(r, self.DEFAULT_ALPHA,
                                                         self.DEFAULT_BETA, self.DEFAULT_GAMMA))
                  for r in run_metrics]
        return [run_id for run_id, _ in sorted(scored, key=lambda x: -x[1])]

    def run(self) -> list[WeightAblationResult]:
        """Execute the full weight grid sweep.

        Returns one WeightAblationResult per (alpha, beta, gamma) triple.
        """
        run_metrics = self._get_run_metrics()
        if not run_metrics:
            return []

        default_ranking = self._get_default_ranking(run_metrics)
        results = []

        # Generate all (alpha, beta, gamma) triples summing to 1.0 within step grid
        vals = [round(v * self._step, 2) for v in range(1, int(1.0 / self._step))]
        for alpha, beta in itertools.product(vals, vals):
            gamma = round(1.0 - alpha - beta, 2)
            if gamma <= 0 or gamma > 1.0:
                continue

            scored = [
                (r["run_id"], self._compute_composite(r, alpha, beta, gamma))
                for r in run_metrics
            ]
            ranking = sorted(scored, key=lambda x: -x[1])
            current_order = [run_id for run_id, _ in ranking]

            # Count rank changes from default
            rank_changes = sum(
                1 for i, run_id in enumerate(current_order)
                if i < len(default_ranking) and default_ranking[i] != run_id
            )

            results.append(WeightAblationResult(
                alpha=alpha,
                beta=beta,
                gamma=gamma,
                run_rankings=ranking,
                rank_changes_from_default=rank_changes,
            ))

        return results

    def sensitivity_report(self) -> dict:
        """Summarize how sensitive the leaderboard is to weight choices.

        Returns:
            dict with keys: max_rank_changes, mean_rank_changes,
            most_stable_weights, most_unstable_weights
        """
        results = self.run()
        if not results:
            return {"max_rank_changes": 0, "mean_rank_changes": 0.0}

        changes = [r.rank_changes_from_default for r in results]
        stable = min(results, key=lambda r: r.rank_changes_from_default)
        unstable = max(results, key=lambda r: r.rank_changes_from_default)

        return {
            "max_rank_changes": max(changes),
            "mean_rank_changes": round(sum(changes) / len(changes), 2),
            "most_stable_weights": {"alpha": stable.alpha, "beta": stable.beta, "gamma": stable.gamma},
            "most_unstable_weights": {"alpha": unstable.alpha, "beta": unstable.beta, "gamma": unstable.gamma},
            "weight_configs_tested": len(results),
        }
