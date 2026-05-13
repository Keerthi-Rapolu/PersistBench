"""Overview page — run selector, summary metrics, suite health."""
from __future__ import annotations

import streamlit as st

st.title("Overview")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

# -----------------------------------------------------------------
# Run selector
# -----------------------------------------------------------------
runs = conn.execute(
    "SELECT run_id, model_id, defense_name, suite, created_at "
    "FROM runs ORDER BY created_at DESC"
).fetchall()

if not runs:
    st.warning("No runs found in database.")
    st.stop()

run_options = {r[0]: f"{r[0]} — {r[1]} / {r[2]} ({r[3]})" for r in runs}
selected = st.selectbox("Select run", list(run_options.keys()),
                        format_func=lambda k: run_options[k])

st.session_state["selected_run_id"] = selected

# -----------------------------------------------------------------
# Summary metric cards
# -----------------------------------------------------------------
m = conn.execute(
    "SELECT aps, rls, ups, composite_score, bdi_10, bdi_50, attack_detected "
    "FROM scenario_metrics WHERE run_id = ?",
    [selected],
).fetchone()

if m is None:
    st.info("No metrics found for this run yet.")
    st.stop()

aps, rls, ups, composite, bdi10, bdi50, detected = m

c1, c2, c3, c4 = st.columns(4)
c1.metric("APS", f"{aps:.4f}", help="Attack Persistence Score (1=fully persisted)")
c2.metric("RLS", f"{rls:.4f}", help="Recovery Latency Score (1=never recovered)")
c3.metric("UPS", f"{ups:.4f}", help="Utility Preservation Score (1=no degradation)")
c4.metric("Composite", f"{composite:.4f}", help="0.45*(1-APS) + 0.35*(1-RLS) + 0.20*UPS")

c5, c6, c7 = st.columns(3)
c5.metric("BDI @ 10%", f"{bdi10:.4f}" if bdi10 is not None else "—")
c6.metric("BDI @ 50%", f"{bdi50:.4f}" if bdi50 is not None else "—")
c7.metric("Attack Detected", "Yes" if detected else "No")

# -----------------------------------------------------------------
# Suite health: all runs summary
# -----------------------------------------------------------------
st.subheader("All runs")
all_metrics = conn.execute(
    "SELECT r.run_id, r.model_id, r.defense_name, r.suite, "
    "sm.aps, sm.rls, sm.ups, sm.composite_score "
    "FROM runs r LEFT JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    "ORDER BY sm.composite_score DESC NULLS LAST"
).fetchall()

if all_metrics:
    import pandas as pd
    df = pd.DataFrame(all_metrics,
                      columns=["run_id", "model", "defense", "suite",
                                "APS", "RLS", "UPS", "Composite"])
    st.dataframe(df, use_container_width=True, hide_index=True)
