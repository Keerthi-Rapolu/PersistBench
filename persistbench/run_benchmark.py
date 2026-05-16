"""PersistBench end-to-end benchmark runner.

Full pipeline:
    scenario YAML
        -> trace generation
        -> DuckDB writes (run, scenario, sessions, turns, memory, provenance)
        -> metric computation
        -> artifact outputs (JSON summary, JSONL trace, provenance graph)
        -> HTML + Markdown reports
        -> console summary

Usage (EchoBackend, default):
    python -m persistbench.run_benchmark \\
        --scenario scenarios/sbmp/sbmp-001.yaml \\
        --run-id run-001 \\
        --db bench.duckdb

Usage (live Claude backend):
    python -m persistbench.run_benchmark \\
        --scenario scenarios/sbmp/sbmp-001.yaml \\
        --llm-backend claude \\
        --llm-model claude-sonnet-4-6 \\
        --run-id run-claude-001 \\
        --db bench.duckdb

    The scenario YAML may also specify an [llm] block; CLI flags take precedence.
    Set ANTHROPIC_API_KEY in the environment before running.

Usage (full suite):
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
from persistbench.engine.backends.base import AgentBackend
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


def _build_backend(scenario: dict, cli_llm_backend: str, cli_llm_model: str) -> AgentBackend:
    """Instantiate the right backend for this run.

    Priority: CLI flags > scenario YAML [llm] block > EchoBackend default.
    """
    # Merge scenario YAML llm block with CLI overrides
    llm_cfg: dict = dict(scenario.get("llm", {}))
    if cli_llm_backend:
        llm_cfg["backend"] = cli_llm_backend
    if cli_llm_model:
        llm_cfg["model"] = cli_llm_model

    backend_name = llm_cfg.get("backend", "echo").lower()

    if backend_name == "echo":
        return EchoBackend()

    if backend_name == "claude":
        from persistbench.engine.backends.claude_backend import ClaudeBackend
        return ClaudeBackend(
            model=llm_cfg.get("model", "claude-sonnet-4-6"),
            system_prompt=llm_cfg.get("system_prompt"),
            max_tokens=int(llm_cfg.get("max_tokens", 512)),
            session_mode=llm_cfg.get("session_mode", "continuous"),
            request_delay=float(llm_cfg.get("request_delay", 0.3)),
        )

    if backend_name == "openai":
        from persistbench.engine.backends.openai_backend import OpenAIBackend
        return OpenAIBackend(
            model=llm_cfg.get("model", "gpt-4o"),
            system_prompt=llm_cfg.get("system_prompt"),
            max_tokens=int(llm_cfg.get("max_tokens", 512)),
            session_mode=llm_cfg.get("session_mode", "continuous"),
            request_delay=float(llm_cfg.get("request_delay", 0.2)),
            temperature=float(llm_cfg.get("temperature", 0.0)),
        )

    raise ValueError(
        f"Unknown llm.backend: {backend_name!r}. "
        "Supported: 'echo', 'claude', 'openai'."
    )


def _print_cost_estimate(scenario: dict, backend: AgentBackend) -> bool:
    """Print a cost estimate for live backends. Returns True to continue, False to abort."""
    from persistbench.engine.backends.claude_backend import ClaudeBackend, estimate_cost
    if not isinstance(backend, ClaudeBackend):
        return True

    est = estimate_cost(scenario, backend.model, backend.session_mode)
    print(f"\n  ┌── Live LLM Cost Estimate ────────────────────────────────")
    print(f"  │  Model:         {backend.model}")
    print(f"  │  Session mode:  {backend.session_mode}")
    print(f"  │  Turns:         ~{est['turns']}")
    print(f"  │  Input tokens:  ~{est['input_tokens']:,}")
    print(f"  │  Output tokens: ~{est['output_tokens']:,}")
    print(f"  │  Est. cost:     ~${est['total_cost_usd']:.3f} USD")
    print(f"  └──────────────────────────────────────────────────────────")
    answer = input("  Proceed? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def run_scenario(
    conn,
    scenario: dict,
    run_id: str,
    artifact_dir: Path,
    backend: AgentBackend = None,
    defense=None,
    skip_cost_prompt: bool = False,
) -> dict:
    """Execute one scenario and return its metrics dict.

    Args:
        backend:          Pre-built backend. If None, EchoBackend is used.
        defense:          DefensePlugin instance. If None, NoDefense is used.
        skip_cost_prompt: Skip the interactive cost-confirmation prompt (e.g. in batch mode).
    """
    if backend is None:
        backend = EchoBackend()

    # Cost estimate gate for live backends
    if not skip_cost_prompt:
        if not _print_cost_estimate(scenario, backend):
            print("  Aborted by user.")
            import sys as _sys
            _sys.exit(0)

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

    # V2.2: read Qdrant config from scenario YAML memory block
    memory_cfg = scenario.get("memory", {})
    qdrant_url = None
    qdrant_top_k = 5
    if memory_cfg.get("backend") == "qdrant_vector":
        qdrant_url  = memory_cfg.get("qdrant_url", ":memory:")
        qdrant_top_k = memory_cfg.get("top_k", 5)

    engine = ReplayEngine(
        conn=conn,
        backend=backend,
        run_id=run_id,
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
        qdrant_url=qdrant_url,
        qdrant_top_k=qdrant_top_k,
        defense=defense,
    )

    backend_label = type(backend).__name__
    print(f"  [{scenario['scenario_id']}] replaying [{backend_label}] ...", end=" ", flush=True)
    metrics = engine.run(trace)
    print(
        f"APS={metrics['aps']:.3f}  RLS={metrics['rls']:.3f}  "
        f"UPS={metrics['ups']:.3f}  composite={metrics['composite_score']:.3f}"
    )

    # Print actual token usage for live backends
    from persistbench.engine.backends.claude_backend import ClaudeBackend
    if isinstance(backend, ClaudeBackend):
        u = backend.usage
        print(f"  [{scenario['scenario_id']}] "
              f"tokens: {u['input_tokens']:,} in / {u['output_tokens']:,} out "
              f"({u['calls']} calls)")

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
    parser.add_argument("--model", default=None,
                        help="Model ID label for the run record. Defaults to "
                             "the llm.model from scenario YAML, or 'echo'.")
    parser.add_argument("--horizon", default="short",
                        help="Horizon label (default: short)")

    # V4: live LLM backend flags
    llm_group = parser.add_argument_group("Live LLM backend (V4)")
    llm_group.add_argument(
        "--llm-backend", default=None, choices=["echo", "claude", "openai"],
        help="Agent backend: 'echo' (deterministic), 'claude' (Anthropic API), "
             "or 'openai' (OpenAI API). Overrides scenario YAML llm.backend. "
             "Default: from YAML or 'echo'.",
    )
    llm_group.add_argument(
        "--llm-model", default=None,
        help="Model ID for live backend (e.g. 'claude-sonnet-4-6'). "
             "Overrides scenario YAML llm.model.",
    )
    llm_group.add_argument(
        "--yes", action="store_true",
        help="Skip interactive cost-confirmation prompt (use in scripts/CI).",
    )

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

    first_scenario = load_scenario(yaml_files[0])
    seed = first_scenario["seed"] if args.scenario else 0

    # Build backend once (shared across all scenarios in the run)
    backend = _build_backend(first_scenario, args.llm_backend, args.llm_model)
    backend_label = type(backend).__name__

    # Instantiate defense plugin
    from persistbench.defense import load_defense
    defense = load_defense(args.defense)
    defense_label = type(defense).__name__

    # Derive model_id label for the run record
    model_id = args.model
    if model_id is None:
        from persistbench.engine.backends.claude_backend import ClaudeBackend
        if isinstance(backend, ClaudeBackend):
            model_id = backend.model
        else:
            model_id = "echo"

    writers.write_run(
        conn,
        run_id=run_id,
        benchmark_ver=BENCHMARK_VER,
        defense_name=defense_label,
        defense_ver="4.0.0",
        model_id=model_id,
        suite=suite,
        horizon=args.horizon,
        seed=seed,
    )

    print(f"\nPersistBench run: {run_id}")
    print(f"  DB:      {args.db}")
    print(f"  Suite:   {suite}  ({len(yaml_files)} scenario(s))")
    print(f"  Backend: {backend_label}  model={model_id}")
    print(f"  Defense: {defense_label}")
    print()

    all_metrics = []
    for i, yf in enumerate(yaml_files):
        scenario = load_scenario(yf)
        # Only show cost prompt once (before the first scenario); skip for echo
        show_prompt = (i == 0) and not args.yes
        metrics = run_scenario(
            conn, scenario, run_id, args.output_dir,
            backend=backend,
            defense=defense,
            skip_cost_prompt=(not show_prompt),
        )
        all_metrics.append(metrics)
        # Reset backend state between scenarios in a suite run
        if i < len(yaml_files) - 1:
            backend.reset()

    finalize_run(conn, run_id, suite, all_metrics, args.output_dir)
    conn.close()

    print(f"\nDone. Run ID: {run_id}")


if __name__ == "__main__":
    main()
