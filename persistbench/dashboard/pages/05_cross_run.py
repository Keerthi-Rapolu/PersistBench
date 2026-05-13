"""Cross-Run Comparison — metrics table, grouped bar chart, delta column."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

st.title("Cross-Run Comparison")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

# -----------------------------------------------------------------
# Run multi-selector
# -----------------------------------------------------------------
all_runs = conn.execute(
    "SELECT run_id, model_id, defense_name, suite FROM runs ORDER BY created_at DESC"
).fetchall()

if len(all_runs) < 2:
    st.info("Need at least 2 runs to compare. Only one run found.")
    st.stop()

run_labels = {r[0]: f"{r[0]} ({r[1]} / {r[2]})" for r in all_runs}
selected = st.multiselect(
    "Select runs to compare (≥ 2)",
    list(run_labels.keys()),
    default=list(run_labels.keys())[:2],
    format_func=lambda k: run_labels[k],
)

if len(selected) < 2:
    st.warning("Select at least 2 runs.")
    st.stop()

# -----------------------------------------------------------------
# Baseline selector
# -----------------------------------------------------------------
baseline = st.radio("Baseline run (for Δ composite)", selected, horizontal=True)

# -----------------------------------------------------------------
# Build comparison dataframe
# -----------------------------------------------------------------
rows = conn.execute(
    f"SELECT r.run_id, r.model_id, r.defense_name, "
    f"sm.aps, sm.rls, sm.ups, sm.composite_score "
    f"FROM runs r LEFT JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    f"WHERE r.run_id IN ({','.join('?' for _ in selected)})",
    selected,
).fetchall()

df = pd.DataFrame(rows, columns=["run_id", "model", "defense",
                                   "APS", "RLS", "UPS", "Composite"])

baseline_composite = df.loc[df["run_id"] == baseline, "Composite"].values
baseline_val = float(baseline_composite[0]) if len(baseline_composite) else 0.0
df["Δ Composite"] = (df["Composite"] - baseline_val).round(4)

sort_col = st.selectbox("Sort by", ["Composite", "APS", "RLS", "UPS", "Δ Composite"])
df = df.sort_values(sort_col, ascending=False).reset_index(drop=True)

st.dataframe(df, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------
# Grouped bar chart
# -----------------------------------------------------------------
st.subheader("Metric comparison")

melted = df.melt(id_vars=["run_id", "model", "defense"],
                 value_vars=["APS", "RLS", "UPS", "Composite"],
                 var_name="metric", value_name="value")

chart = alt.Chart(melted).mark_bar().encode(
    x=alt.X("run_id:N", title="Run"),
    y=alt.Y("value:Q", title="Score", scale=alt.Scale(domain=[0, 1])),
    color=alt.Color("metric:N", title="Metric"),
    column=alt.Column("metric:N", title=""),
    tooltip=["run_id", "metric", "value"],
).properties(width=140, height=280)

st.altair_chart(chart)
