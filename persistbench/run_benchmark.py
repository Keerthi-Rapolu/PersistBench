"""PersistBench end-to-end benchmark runner.

Full pipeline:
    scenario YAML
        -> trace generation
        -> DuckDB writes (run, scenario, sessions, turns, memory, provenance)
        -> metric computation
        -> artifact outputs (JSON summary, JSONL trace, provenance graph)
        -> HTML + Markdown reports
        -> console summary

Usage:
    python -m persistbench.run_benchmark \\
        --scenario scenarios/sbmp/sbmp-001.yaml \\
        --run-id run-001 \\
        --db bench.duckdb \\
        --output-dir artifacts

    python -m persistbench.run_benchmark \\
        --suite SBMP \\
        --run-id run-batch-001 \\
        --db bench.duckdb
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from persistbench.data.generator import generate_trace, load_scenario
from persistbench.db import writers
from persistbench.db.init import get_connection
from persistbench.engine.backends.echo import EchoBackend
from persistbench.engine.replay import ReplayEngine
from persistbench.reporting.artifact_writer import (
    write_governance_events,
    write_metrics_json,
    write_provenance_graph,
    write_replay_trace,
    write_run_summary,
)
from persistbench.reporting.report_generator import generate_report

SCENARIOS_DIR = _ROOT / "scenarios"
BENCHMARK_VER = "1.0.0"


def run_scenario(
    conn,
    scenario: dict,
    run_id: str,
    artifact_dir: Path,
) -> dict:
    """Execute one scenario and return its metrics dict."""
    print(f"  [{scenario['scenario_id']}] generating trace ...", end=" ", flush=True)
    trace = generate_trace(scenario)
    print(f"{len(trace)} turns")

    writers.write_scenario(
        conn,
        scenario_id=scenario["scenario_id"],
        suite=scenario["suite"],
        variant=scenario["variant"],
        domain=scenario["domain"],
        difficulty=scenario["difficulty"],
        session_count=scenario["session_count"],
        attack_class=scenario.get("attack", {}).get("class", "none"),
        benchmark_ver=BENCHMARK_VER,
        fragment_count=len(scenario.get("attack", {}).get("fragments", [])),
    )

    engine = ReplayEngine(
        conn=conn,
        backend=EchoBackend(),
        run_id=run_id,
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
    )

    print(f"  [{scenario['scenario_id']}] replaying ...", end=" ", flush=True)
    metrics = engine.run(trace)
    print(
        f"APS={metrics['aps']:.3f}  RLS={metrics['rls']:.3f}  "
        f"UPS={metrics['ups']:.3f}  composite={metrics['composite_score']:.3f}"
    )

    # Write per-scenario artifacts
    write_replay_trace(trace, f"{run_id}_{scenario['scenario_id']}", artifact_dir / "replay_traces")
    write_provenance_graph(conn, run_id, artifact_dir / "provenance")
    write_governance_events(conn, run_id, artifact_dir / "exports")

    return metrics


def finalize_run(conn, run_id: str, suite: str, all_metrics: list[dict],
                 artifact_dir: Path) -> None:
    """Write suite-level metrics, run summary, and reports."""
    if not all_metrics:
        return

    aps_vals = [m["aps"] for m in all_metrics]
    rls_vals = [m["rls"] for m in all_metrics]
    ups_vals = [m["ups"] for m in all_metrics]
    comp_vals = [m["composite_score"] for m in all_metrics]

    import statistics
    writers.write_suite_metrics(
        conn,
        run_id=run_id,
        suite=suite,
        aps_mean=round(statistics.mean(aps_vals), 6),
        aps_std=round(statistics.stdev(aps_vals) if len(aps_vals) > 1 else 0.0, 6),
        rls_mean=round(statistics.mean(rls_vals), 6),
        rls_std=round(statistics.stdev(rls_vals) if len(rls_vals) > 1 else 0.0, 6),
        ups=round(statistics.mean(ups_vals), 6),
        composite_score=round(statistics.mean(comp_vals), 6),
        scenario_count=len(all_metrics),
    )

    write_run_summary(conn, run_id, artifact_dir / "runs")
    write_metrics_json(conn, run_id, artifact_dir / "runs")
    generate_report(conn, run_id, artifact_dir / "reports", fmt="html")
    generate_report(conn, run_id, artifact_dir / "reports", fmt="md")

    print(f"\n  Artifacts written to: {artifact_dir}")
    print(f"  HTML report: {artifact_dir / 'reports' / (run_id + '_report.html')}")


def _ensure_artifact_dirs(base: Path) -> None:
    for sub in ("runs", "reports", "replay_traces", "provenance", "exports"):
        (base / sub).mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PersistBench end-to-end benchmark runner"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", type=Path, help="Single scenario YAML")
    group.add_argument("--suite", choices=["SBMP", "TSCC", "CACP"],
                       help="Run all scenarios in a suite")

    parser.add_argument("--run-id", default=None,
                        help="Run ID (auto-generated if omitted)")
    parser.add_argument("--db", type=Path, default=Path("bench.duckdb"),
                        help="DuckDB path (default: bench.duckdb)")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"),
                        help="Artifact output directory (default: artifacts/)")
    parser.add_argument("--defense", default="NoDefense",
                        help="Defense name (default: NoDefense)")
    parser.add_argument("--model", default="echo",
                        help="Model ID (default: echo)")
    parser.add_argument("--horizon", default="short",
                        help="Horizon label (default: short)")
    args = parser.parse_args()

    run_id = args.run_id or f"run-{uuid.uuid4().hex[:8]}"
    _ensure_artifact_dirs(args.output_dir)

    conn = get_connection(args.db)

    # Collect scenario YAMLs
    if args.scenario:
        yaml_files = [args.scenario]
        suite = load_scenario(args.scenario)["suite"]
    else:
        suite_dir = SCENARIOS_DIR / args.suite.lower()
        yaml_files = sorted(suite_dir.glob("*.yaml"))
        suite = args.suite
        if not yaml_files:
            print(f"No YAML files found in {suite_dir}")
            sys.exit(1)

    # Seed from first scenario (or 0 for multi-scenario runs)
    first_scenario = load_scenario(yaml_files[0])
    seed = first_scenario["seed"] if args.scenario else 0

    writers.write_run(
        conn,
        run_id=run_id,
        benchmark_ver=BENCHMARK_VER,
        defense_name=args.defense,
        defense_ver="1.0.0",
        model_id=args.model,
        suite=suite,
        horizon=args.horizon,
        seed=seed,
    )

    print(f"\nPersistBench run: {run_id}")
    print(f"  DB:     {args.db}")
    print(f"  Suite:  {suite}  ({len(yaml_files)} scenario(s))")
    print()

    all_metrics = []
    for yf in yaml_files:
        scenario = load_scenario(yf)
        metrics = run_scenario(conn, scenario, run_id, args.output_dir)
        all_metrics.append(metrics)

    finalize_run(conn, run_id, suite, all_metrics, args.output_dir)
    conn.close()

    print(f"\nDone. Run ID: {run_id}")


if __name__ == "__main__":
    main()
