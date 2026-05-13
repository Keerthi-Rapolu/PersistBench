"""Forgetting Validation Explorer — FVS, probe sessions, resurfacing pathways."""
from __future__ import annotations

import pandas as pd
import streamlit as st

st.title("Forgetting Validation")

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

# -----------------------------------------------------------------
# Check v2 deletion records
# -----------------------------------------------------------------
try:
    del_count = conn.execute(
        "SELECT count(*) FROM deletion_records WHERE run_id = ?", [run_id]
    ).fetchone()[0]
except Exception:
    del_count = 0

if del_count == 0:
    st.warning(
        "Forgetting validation requires v2 deletion records — "
        "no deletions found for this run. "
        "The session table and BDI values below are still shown."
    )

# -----------------------------------------------------------------
# Session explorer — probe sessions with BDI
# -----------------------------------------------------------------
st.subheader("Probe session BDI values")

rows = conn.execute(
    "SELECT session_id, is_attack_session, is_trigger_session, "
    "is_probe_session, turn_count, bdi_value, safety_score "
    "FROM sessions WHERE run_id = ? ORDER BY session_id",
    [run_id],
).fetchall()

cols = ["session_id", "is_attack_session", "is_trigger_session",
        "is_probe_session", "turn_count", "bdi_value", "safety_score"]
df = pd.DataFrame(rows, columns=cols)

# Selector
total = len(df)
s_min, s_max = int(df["session_id"].min()), int(df["session_id"].max())
sel_range = st.slider("Session range", s_min, s_max, (s_min, s_max))
filtered = df[(df["session_id"] >= sel_range[0]) & (df["session_id"] <= sel_range[1])]

st.dataframe(filtered, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------
# Resurfacing pathway chart (v1: no deletions → no resurfacing)
# -----------------------------------------------------------------
st.subheader("Resurfacing pathways")

probe_df = filtered[filtered["is_probe_session"] == True].copy()
if probe_df.empty:
    st.info("No probe sessions in selected range.")
else:
    import altair as alt
    probe_df["bdi_value"] = probe_df["bdi_value"].fillna(0.0)
    chart = alt.Chart(probe_df).mark_line(point=True).encode(
        x=alt.X("session_id:Q", title="Session"),
        y=alt.Y("bdi_value:Q", title="BDI value",
                scale=alt.Scale(domain=[0, 1])),
        tooltip=["session_id", "bdi_value", "safety_score"],
    ).properties(height=280, title="BDI across probe sessions")
    st.altair_chart(chart, use_container_width=True)

    if del_count == 0:
        st.caption(
            "No deletions recorded — resurfacing analysis requires v2 deletion logic."
        )
