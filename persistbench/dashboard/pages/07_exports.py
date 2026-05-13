"""Exportable Research Artifacts — in-memory download buttons."""
from __future__ import annotations

import io
import json

import streamlit as st

st.title("Exports")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

run_id = st.session_state.get("selected_run_id")
if not run_id:
    runs = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()
    if not runs:
        st.warning("No runs in database.")
        st.stop()
    run_id = st.selectbox("Run", [r[0] for r in runs])

st.caption(f"Exporting artifacts for run: **{run_id}**")

# -----------------------------------------------------------------
# CSV — scenario_metrics joined with runs
# -----------------------------------------------------------------
csv_rows = conn.execute(
    "SELECT r.run_id, r.model_id, r.defense_name, r.suite, r.horizon, r.seed, "
    "sm.scenario_id, sm.aps, sm.rls, sm.ups, sm.bdi_10, sm.bdi_50, "
    "sm.composite_score, sm.attack_detected, sm.detection_session, "
    "sm.recovery_session, sm.flags_emitted, sm.false_positives "
    "FROM runs r JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    "WHERE r.run_id = ?",
    [run_id],
).fetchall()
csv_cols = [
    "run_id", "model_id", "defense_name", "suite", "horizon", "seed",
    "scenario_id", "aps", "rls", "ups", "bdi_10", "bdi_50",
    "composite_score", "attack_detected", "detection_session",
    "recovery_session", "flags_emitted", "false_positives",
]
csv_buf = io.StringIO()
csv_buf.write(",".join(csv_cols) + "\n")
for row in csv_rows:
    csv_buf.write(",".join("" if v is None else str(v) for v in row) + "\n")

st.download_button(
    label="Download CSV",
    data=csv_buf.getvalue().encode("utf-8"),
    file_name=f"{run_id}_metrics.csv",
    mime="text/csv",
)

# -----------------------------------------------------------------
# JSON — full run summary
# -----------------------------------------------------------------
run_row = conn.execute(
    "SELECT run_id, benchmark_ver, defense_name, defense_ver, model_id, "
    "suite, horizon, seed, created_at FROM runs WHERE run_id = ?",
    [run_id],
).fetchone()
run_cols = ["run_id", "benchmark_ver", "defense_name", "defense_ver",
            "model_id", "suite", "horizon", "seed", "created_at"]
run_data = dict(zip(run_cols, run_row)) if run_row else {}
scenarios = [dict(zip(csv_cols[6:], r[6:])) for r in csv_rows]
run_data["scenarios"] = scenarios
json_str = json.dumps(run_data, sort_keys=True, indent=2, default=str)

st.download_button(
    label="Download JSON",
    data=json_str.encode("utf-8"),
    file_name=f"{run_id}_summary.json",
    mime="application/json",
)

# -----------------------------------------------------------------
# Markdown report
# -----------------------------------------------------------------
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from persistbench.reporting.report_generator import generate_report as _gen
    md_buf = io.StringIO()

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = _gen(conn, run_id, tmpdir, fmt="md")
        md_content = md_path.read_text(encoding="utf-8")

    st.download_button(
        label="Download Markdown",
        data=md_content.encode("utf-8"),
        file_name=f"{run_id}_report.md",
        mime="text/markdown",
    )

    # HTML report
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = _gen(conn, run_id, tmpdir, fmt="html")
        html_content = html_path.read_text(encoding="utf-8")

    st.download_button(
        label="Download HTML",
        data=html_content.encode("utf-8"),
        file_name=f"{run_id}_report.html",
        mime="text/html",
    )
except Exception as exc:
    st.warning(f"Report generator unavailable: {exc}")
