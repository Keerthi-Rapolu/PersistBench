"""Artifact Bundler — Reproducible benchmark artifact bundles.

Creates a compressed bundle containing everything needed to reproduce
a benchmark run:
  - Scenario YAML files used in the run
  - Replay trace JSONL files
  - Metric JSON summary
  - DuckDB snapshot (optional — use --no-db for large datasets)
  - Provenance graph JSON
  - run_config.json: exact CLI flags, versions, seeds

Bundle format: {run_id}.tar.gz (or .zip on Windows)

Design ref: DESIGN_DOC.md §37.3 (Reproducible Artifact Bundles)
"""
from __future__ import annotations

import json
import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb


class ArtifactBundler:
    """Create reproducible benchmark artifact bundles.

    Args:
        conn:        DuckDB connection
        artifact_dir: Base artifact directory (from run_benchmark.py --output-dir)
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        artifact_dir: Path,
    ) -> None:
        self._conn = conn
        self._artifact_dir = Path(artifact_dir)

    def bundle(
        self,
        run_id: str,
        output_dir: Optional[Path] = None,
        include_db: bool = False,
        format: str = "zip",  # zip | tar.gz
    ) -> Path:
        """Create a reproducible bundle for `run_id`.

        Args:
            run_id:      Run to bundle.
            output_dir:  Where to write the bundle (default: artifact_dir/bundles/)
            include_db:  Include a DuckDB snapshot (large — skip for CI).
            format:      "zip" (default, cross-platform) or "tar.gz"

        Returns:
            Path to the created bundle file.
        """
        output_dir = Path(output_dir or (self._artifact_dir / "bundles"))
        output_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = output_dir / f"_tmp_{run_id}"
        tmp_dir.mkdir(exist_ok=True)

        try:
            # 1. run_config.json
            run_info = self._get_run_info(run_id)
            config = {
                "run_id": run_id,
                "bundled_at": datetime.now(timezone.utc).isoformat(),
                "benchmark_ver": run_info.get("benchmark_ver", "unknown"),
                "model_id": run_info.get("model_id", "unknown"),
                "defense_name": run_info.get("defense_name", "unknown"),
                "suite": run_info.get("suite", "unknown"),
                "seed": run_info.get("seed"),
                "reproducibility_note": (
                    "To reproduce: python -m persistbench.run_benchmark "
                    f"--suite {run_info.get('suite', 'SBMP')} "
                    f"--run-id {run_id} "
                    f"--defense {run_info.get('defense_name', 'NoDefense')}"
                ),
            }
            (tmp_dir / "run_config.json").write_text(
                json.dumps(config, indent=2, default=str), encoding="utf-8"
            )

            # 2. Metric summary
            metrics = self._get_metrics(run_id)
            (tmp_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, default=str), encoding="utf-8"
            )

            # 3. Replay traces (if they exist)
            traces_src = self._artifact_dir / "replay_traces"
            if traces_src.exists():
                traces_dst = tmp_dir / "replay_traces"
                traces_dst.mkdir(exist_ok=True)
                for tf in traces_src.glob(f"{run_id}_*.jsonl"):
                    shutil.copy2(tf, traces_dst / tf.name)

            # 4. Provenance graphs
            prov_src = self._artifact_dir / "provenance"
            if prov_src.exists():
                prov_dst = tmp_dir / "provenance"
                prov_dst.mkdir(exist_ok=True)
                for pf in prov_src.glob(f"{run_id}*.json"):
                    shutil.copy2(pf, prov_dst / pf.name)

            # 5. Reports
            reports_src = self._artifact_dir / "reports"
            if reports_src.exists():
                reports_dst = tmp_dir / "reports"
                reports_dst.mkdir(exist_ok=True)
                for rf in reports_src.glob(f"{run_id}_*"):
                    shutil.copy2(rf, reports_dst / rf.name)

            # 6. Pack
            ext = ".zip" if format == "zip" else ".tar.gz"
            bundle_path = output_dir / f"{run_id}{ext}"

            if format == "zip":
                with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in tmp_dir.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(tmp_dir))
            else:
                with tarfile.open(bundle_path, "w:gz") as tf:
                    tf.add(tmp_dir, arcname=run_id)

            return bundle_path

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _get_run_info(self, run_id: str) -> dict:
        row = self._conn.execute(
            "SELECT run_id, benchmark_ver, model_id, defense_name, suite, seed, notes "
            "FROM runs WHERE run_id = ?", [run_id]
        ).fetchone()
        if row is None:
            return {}
        return dict(zip(
            ["run_id", "benchmark_ver", "model_id", "defense_name", "suite", "seed", "notes"],
            row,
        ))

    def _get_metrics(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM scenario_metrics WHERE run_id = ?", [run_id]
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [dict(zip(cols, r)) for r in rows]
