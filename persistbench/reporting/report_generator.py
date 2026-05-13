"""Generate human-readable benchmark reports.

Supported formats: html, md, json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal


def generate_report(
    conn,
    run_id: str,
    out_dir: str | Path,
    fmt: Literal["html", "md", "json"] = "html",
) -> Path:
    """Generate a benchmark report for a completed run.

    Args:
        conn:    DuckDB connection (read-only is fine).
        run_id:  Run identifier.
        out_dir: Directory to write the report.
        fmt:     Output format — "html", "md", or "json".

    Returns:
        Path to the written report file.
    """
    out_dir = Path(out_dir)
    data = _collect(conn, run_id)

    if fmt == "json":
        out_path = out_dir / f"{run_id}_report.json"
        out_path.write_text(
            json.dumps(data, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
    elif fmt == "md":
        out_path = out_dir / f"{run_id}_report.md"
        out_path.write_text(_render_md(data), encoding="utf-8")
    else:
        out_path = out_dir / f"{run_id}_report.html"
        out_path.write_text(_render_html(data), encoding="utf-8")

    return out_path


# -----------------------------------------------------------------
# Data collection
# -----------------------------------------------------------------

def _collect(conn, run_id: str) -> dict:
    run_row = conn.execute(
        "SELECT run_id, benchmark_ver, defense_name, defense_ver, model_id, "
        "suite, horizon, seed, created_at FROM runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if run_row is None:
        raise ValueError(f"run_id {run_id!r} not found")

    run_cols = ["run_id", "benchmark_ver", "defense_name", "defense_ver",
                "model_id", "suite", "horizon", "seed", "created_at"]
    run_meta = dict(zip(run_cols, run_row))

    # Core metrics
    m_row = conn.execute(
        "SELECT scenario_id, aps, rls, ups, bdi_10, bdi_50, composite_score, "
        "attack_detected, detection_session, recovery_session, "
        "flags_emitted, false_positives "
        "FROM scenario_metrics WHERE run_id = ?",
        [run_id],
    ).fetchone()
    m_cols = ["scenario_id", "aps", "rls", "ups", "bdi_10", "bdi_50",
              "composite_score", "attack_detected", "detection_session",
              "recovery_session", "flags_emitted", "false_positives"]
    metrics = dict(zip(m_cols, m_row)) if m_row else {}

    # Scenario breakdown
    sess_rows = conn.execute(
        "SELECT session_id, is_attack_session, is_trigger_session, "
        "is_probe_session, turn_count, bdi_value, safety_score "
        "FROM sessions WHERE run_id = ? ORDER BY session_id",
        [run_id],
    ).fetchall()
    sess_cols = ["session_id", "is_attack_session", "is_trigger_session",
                 "is_probe_session", "turn_count", "bdi_value", "safety_score"]
    sessions = [dict(zip(sess_cols, r)) for r in sess_rows]

    # Provenance summary
    prov_rows = conn.execute(
        "SELECT count(*) as event_count FROM provenance_events WHERE run_id = ?",
        [run_id],
    ).fetchone()
    fragment_count = conn.execute(
        "SELECT count(DISTINCT adversarial_fragment_id) FROM memory_entries "
        "WHERE run_id = ? AND is_adversarial = TRUE",
        [run_id],
    ).fetchone()[0]

    provenance = {
        "event_count": prov_rows[0] if prov_rows else 0,
        "fragment_count": fragment_count,
    }

    # Defense performance
    flag_count = conn.execute(
        "SELECT count(*) FROM defense_flags WHERE run_id = ?", [run_id]
    ).fetchone()[0]
    defense = {
        "active": run_meta.get("defense_name") not in (None, "NoDefense"),
        "flags_emitted": flag_count,
        "false_positives": metrics.get("false_positives", 0),
    }

    return {
        "run": run_meta,
        "metrics": metrics,
        "sessions": sessions,
        "provenance": provenance,
        "defense": defense,
    }


# -----------------------------------------------------------------
# Markdown renderer
# -----------------------------------------------------------------

def _render_md(data: dict) -> str:
    run = data["run"]
    m = data["metrics"]
    prov = data["provenance"]
    defense = data["defense"]

    lines = [
        f"# PersistBench Run Report: `{run['run_id']}`",
        "",
        "## 1. Run Metadata",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Model | {run.get('model_id', '—')} |",
        f"| Defense | {run.get('defense_name', '—')} v{run.get('defense_ver', '—')} |",
        f"| Suite | {run.get('suite', '—')} |",
        f"| Horizon | {run.get('horizon', '—')} |",
        f"| Seed | {run.get('seed', '—')} |",
        f"| Benchmark ver | {run.get('benchmark_ver', '—')} |",
        f"| Created | {run.get('created_at', '—')} |",
        "",
        "## 2. Core Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| APS (Attack Persistence Score) | {_fmt(m.get('aps'))} |",
        f"| RLS (Recovery Latency Score) | {_fmt(m.get('rls'))} |",
        f"| UPS (Utility Preservation Score) | {_fmt(m.get('ups'))} |",
        f"| BDI @ 10% | {_fmt(m.get('bdi_10'))} |",
        f"| BDI @ 50% | {_fmt(m.get('bdi_50'))} |",
        f"| Composite Score | **{_fmt(m.get('composite_score'))}** |",
        "",
        "## 3. Scenario Breakdown",
        "",
        "| Session | Attack | Trigger | Probe | Turns | BDI | Safety |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in data["sessions"]:
        lines.append(
            f"| {s['session_id']} "
            f"| {'Y' if s['is_attack_session'] else ''} "
            f"| {'Y' if s['is_trigger_session'] else ''} "
            f"| {'Y' if s['is_probe_session'] else ''} "
            f"| {s['turn_count']} "
            f"| {_fmt(s.get('bdi_value'))} "
            f"| {_fmt(s.get('safety_score'))} |"
        )

    lines += [
        "",
        "## 4. Provenance Summary",
        "",
        f"- Adversarial fragments: {prov['fragment_count']}",
        f"- Provenance events: {prov['event_count']}",
        "",
        "## 5. Defense Performance",
        "",
    ]
    if not defense["active"]:
        lines.append("_No active defense (NoDefense baseline)._")
    else:
        lines += [
            f"- Flags emitted: {defense['flags_emitted']}",
            f"- False positives: {defense['false_positives']}",
        ]

    return "\n".join(lines) + "\n"


# -----------------------------------------------------------------
# HTML renderer
# -----------------------------------------------------------------

def _render_html(data: dict) -> str:
    run = data["run"]
    m = data["metrics"]
    prov = data["provenance"]
    defense = data["defense"]

    sess_rows = "".join(
        f"<tr><td>{s['session_id']}</td>"
        f"<td>{'Y' if s['is_attack_session'] else ''}</td>"
        f"<td>{'Y' if s['is_trigger_session'] else ''}</td>"
        f"<td>{'Y' if s['is_probe_session'] else ''}</td>"
        f"<td>{s['turn_count']}</td>"
        f"<td>{_fmt(s.get('bdi_value'))}</td>"
        f"<td>{_fmt(s.get('safety_score'))}</td></tr>"
        for s in data["sessions"]
    )

    defense_html = (
        "<p><em>No active defense (NoDefense baseline).</em></p>"
        if not defense["active"]
        else f"<p>Flags emitted: {defense['flags_emitted']}<br>"
             f"False positives: {defense['false_positives']}</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PersistBench Report: {run['run_id']}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; color: #222; }}
  h1, h2 {{ border-bottom: 1px solid #ddd; padding-bottom: .3em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: .4em .7em; text-align: left; }}
  th {{ background: #f5f5f5; }}
  .metric-value {{ font-weight: bold; color: #0066cc; }}
</style>
</head>
<body>
<h1>PersistBench Run Report: <code>{run['run_id']}</code></h1>

<h2>1. Run Metadata</h2>
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Model</td><td>{run.get('model_id', '—')}</td></tr>
<tr><td>Defense</td><td>{run.get('defense_name', '—')} v{run.get('defense_ver', '—')}</td></tr>
<tr><td>Suite</td><td>{run.get('suite', '—')}</td></tr>
<tr><td>Horizon</td><td>{run.get('horizon', '—')}</td></tr>
<tr><td>Seed</td><td>{run.get('seed', '—')}</td></tr>
<tr><td>Benchmark ver</td><td>{run.get('benchmark_ver', '—')}</td></tr>
<tr><td>Created</td><td>{run.get('created_at', '—')}</td></tr>
</table>

<h2>2. Core Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>APS (Attack Persistence Score)</td><td class="metric-value">{_fmt(m.get('aps'))}</td></tr>
<tr><td>RLS (Recovery Latency Score)</td><td class="metric-value">{_fmt(m.get('rls'))}</td></tr>
<tr><td>UPS (Utility Preservation Score)</td><td class="metric-value">{_fmt(m.get('ups'))}</td></tr>
<tr><td>BDI @ 10%</td><td class="metric-value">{_fmt(m.get('bdi_10'))}</td></tr>
<tr><td>BDI @ 50%</td><td class="metric-value">{_fmt(m.get('bdi_50'))}</td></tr>
<tr><td>Composite Score</td><td class="metric-value">{_fmt(m.get('composite_score'))}</td></tr>
</table>

<h2>3. Scenario Breakdown</h2>
<table>
<tr><th>Session</th><th>Attack</th><th>Trigger</th><th>Probe</th>
    <th>Turns</th><th>BDI</th><th>Safety</th></tr>
{sess_rows}
</table>

<h2>4. Provenance Summary</h2>
<p>Adversarial fragments: {prov['fragment_count']}<br>
Provenance events: {prov['event_count']}</p>

<h2>5. Defense Performance</h2>
{defense_html}
</body>
</html>
"""


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)
