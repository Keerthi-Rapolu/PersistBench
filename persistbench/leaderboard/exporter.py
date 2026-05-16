"""Leaderboard Exporter — HuggingFace-style evaluation format export.

Exports benchmark results to:
  1. JSON: per-run summary with all metrics (HuggingFace model card compatible)
  2. JSONL: per-scenario results for fine-grained analysis
  3. CSV: leaderboard table for spreadsheet tools
  4. Markdown: formatted leaderboard for README embedding

Design ref: DESIGN_DOC.md §37 (Benchmark Export Infrastructure)
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb


@dataclass
class LeaderboardEntry:
    """A single benchmark submission result."""
    run_id: str
    model_id: str
    defense_name: str
    suite: str
    benchmark_ver: str
    created_at: str

    # Core metrics
    aps_mean: float
    rls_mean: float
    ups: float
    composite_score: float

    # Extended metrics
    fvs_mean: Optional[float] = None
    leakage_rate_mean: Optional[float] = None
    fss_mean: Optional[float] = None
    cra_mean: Optional[float] = None
    mts_mean: Optional[float] = None
    prs_mean: Optional[float] = None
    res_mean: Optional[float] = None

    # Run metadata
    scenario_count: int = 0
    notes: Optional[str] = None

    def rank_score(self) -> float:
        """Primary ranking score: composite_score (higher = better defense)."""
        return self.composite_score


class LeaderboardExporter:
    """Export benchmark results to multiple output formats.

    Args:
        conn: DuckDB connection to bench.duckdb
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def get_leaderboard_entries(
        self,
        suite: Optional[str] = None,
        min_scenarios: int = 1,
    ) -> list[LeaderboardEntry]:
        """Query all runs and compute leaderboard entries.

        Args:
            suite:         Filter by suite (SBMP | TSCC | CACP | None = all)
            min_scenarios: Minimum number of scenarios to include a run
        """
        suite_filter = "AND r.suite = ?" if suite else ""
        params = [suite] if suite else []

        rows = self._conn.execute(f"""
            SELECT
                r.run_id,
                r.model_id,
                r.defense_name,
                r.suite,
                r.benchmark_ver,
                r.created_at,
                r.notes,
                COUNT(sm.scenario_id)           AS scenario_count,
                AVG(sm.aps)                     AS aps_mean,
                AVG(sm.rls)                     AS rls_mean,
                AVG(sm.ups)                     AS ups_mean,
                AVG(sm.composite_score)         AS composite_mean,
                AVG(sm.fvs)                     AS fvs_mean,
                AVG(sm.leakage_rate)            AS leakage_rate_mean,
                AVG(sm.fss)                     AS fss_mean,
                AVG(sm.cra)                     AS cra_mean,
                AVG(sm.mts_mean)                AS mts_mean,
                AVG(sm.prs_mean)                AS prs_mean,
                AVG(sm.res_mid)                 AS res_mean
            FROM runs r
            LEFT JOIN scenario_metrics sm
              ON sm.run_id = r.run_id
            WHERE 1=1 {suite_filter}
            GROUP BY r.run_id, r.model_id, r.defense_name, r.suite,
                     r.benchmark_ver, r.created_at, r.notes
            HAVING COUNT(sm.scenario_id) >= ?
            ORDER BY composite_mean DESC NULLS LAST
        """, params + [min_scenarios]).fetchall()

        columns = [
            "run_id", "model_id", "defense_name", "suite", "benchmark_ver",
            "created_at", "notes", "scenario_count",
            "aps_mean", "rls_mean", "ups_mean", "composite_mean",
            "fvs_mean", "leakage_rate_mean", "fss_mean", "cra_mean",
            "mts_mean", "prs_mean", "res_mean",
        ]
        entries = []
        for row in rows:
            d = dict(zip(columns, row))
            entries.append(LeaderboardEntry(
                run_id=d["run_id"],
                model_id=d["model_id"],
                defense_name=d["defense_name"],
                suite=d["suite"],
                benchmark_ver=d["benchmark_ver"],
                created_at=str(d.get("created_at", "")),
                notes=d.get("notes"),
                scenario_count=int(d["scenario_count"] or 0),
                aps_mean=round(d["aps_mean"] or 0.0, 4),
                rls_mean=round(d["rls_mean"] or 0.0, 4),
                ups=round(d["ups_mean"] or 0.0, 4),
                composite_score=round(d["composite_mean"] or 0.0, 4),
                fvs_mean=round(d["fvs_mean"], 4) if d["fvs_mean"] is not None else None,
                leakage_rate_mean=round(d["leakage_rate_mean"], 4) if d["leakage_rate_mean"] is not None else None,
                fss_mean=round(d["fss_mean"], 4) if d["fss_mean"] is not None else None,
                cra_mean=round(d["cra_mean"], 4) if d["cra_mean"] is not None else None,
                mts_mean=round(d["mts_mean"], 4) if d["mts_mean"] is not None else None,
                prs_mean=round(d["prs_mean"], 4) if d["prs_mean"] is not None else None,
                res_mean=round(d["res_mean"], 4) if d["res_mean"] is not None else None,
            ))
        return entries

    def export_json(self, output_path: Path, **kwargs) -> Path:
        """Export full leaderboard as JSON (HuggingFace model card compatible)."""
        entries = self.get_leaderboard_entries(**kwargs)
        data = {
            "benchmark": "PersistBench",
            "version": "4.0.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entries": [asdict(e) for e in entries],
        }
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return output_path

    def export_jsonl(self, output_path: Path, **kwargs) -> Path:
        """Export per-scenario results as JSONL."""
        rows = self._conn.execute("""
            SELECT
                r.run_id, r.model_id, r.defense_name, r.suite,
                sm.scenario_id, sm.aps, sm.rls, sm.ups, sm.composite_score,
                sm.fvs, sm.leakage_rate, sm.fss, sm.cra, sm.mts_mean,
                sm.prs_mean, sm.res_mid, sm.attack_detected,
                sm.detection_session, sm.recovery_session,
                sm.flags_emitted, sm.false_positives
            FROM scenario_metrics sm
            JOIN runs r ON r.run_id = sm.run_id
            ORDER BY r.run_id, sm.scenario_id
        """).fetchall()

        columns = [
            "run_id", "model_id", "defense_name", "suite",
            "scenario_id", "aps", "rls", "ups", "composite_score",
            "fvs", "leakage_rate", "fss", "cra", "mts_mean",
            "prs_mean", "res_mid", "attack_detected",
            "detection_session", "recovery_session",
            "flags_emitted", "false_positives",
        ]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for row in rows:
                record = dict(zip(columns, row))
                f.write(json.dumps(record, default=str) + "\n")
        return output_path

    def export_csv(self, output_path: Path, **kwargs) -> Path:
        """Export leaderboard as CSV for spreadsheet tools."""
        entries = self.get_leaderboard_entries(**kwargs)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            if not entries:
                return output_path
            writer = csv.DictWriter(f, fieldnames=list(asdict(entries[0]).keys()))
            writer.writeheader()
            for e in entries:
                writer.writerow(asdict(e))
        return output_path

    def export_markdown(self, output_path: Path, **kwargs) -> Path:
        """Export leaderboard as a Markdown table."""
        entries = self.get_leaderboard_entries(**kwargs)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# PersistBench V4 Leaderboard",
            "",
            f"> Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "| Rank | Run ID | Model | Defense | Suite | Scenarios | APS↓ | RLS↓ | UPS↑ | Composite↑ | FVS↑ |",
            "|------|--------|-------|---------|-------|-----------|------|------|------|------------|------|",
        ]
        for i, e in enumerate(entries, 1):
            fvs = f"{e.fvs_mean:.3f}" if e.fvs_mean is not None else "—"
            lines.append(
                f"| {i} | {e.run_id} | {e.model_id} | {e.defense_name} | "
                f"{e.suite} | {e.scenario_count} | "
                f"{e.aps_mean:.3f} | {e.rls_mean:.3f} | {e.ups:.3f} | "
                f"{e.composite_score:.3f} | {fvs} |"
            )
        lines.append("")
        lines.append("*APS↓: lower is better (fewer fragments persisted). "
                     "Composite↑: higher is better.*")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def export_all(self, output_dir: Path, **kwargs) -> dict[str, Path]:
        """Export to all formats. Returns dict of format → path."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return {
            "json":     self.export_json(output_dir / f"leaderboard_{ts}.json", **kwargs),
            "jsonl":    self.export_jsonl(output_dir / f"scenarios_{ts}.jsonl", **kwargs),
            "csv":      self.export_csv(output_dir / f"leaderboard_{ts}.csv", **kwargs),
            "markdown": self.export_markdown(output_dir / f"LEADERBOARD_{ts}.md", **kwargs),
        }
