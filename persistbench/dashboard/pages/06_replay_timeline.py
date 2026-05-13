"""Replay Timeline Explorer — session-by-session attack timeline with turn detail."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

st.title("Replay Timeline")

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
# Fetch all turns
# -----------------------------------------------------------------
turn_rows = conn.execute(
    "SELECT session_id, turn_id, role, content_hash, "
    "is_benign, is_trigger, is_probe, fragment_id "
    "FROM turns WHERE run_id = ? ORDER BY session_id, turn_id",
    [run_id],
).fetchall()

if not turn_rows:
    st.info("No turns found for this run.")
    st.stop()

turn_cols = ["session_id", "turn_id", "role", "content_hash",
             "is_benign", "is_trigger", "is_probe", "fragment_id"]
df = pd.DataFrame(turn_rows, columns=turn_cols)


def _turn_type(row):
    if row["is_trigger"]:
        return "trigger"
    if row["fragment_id"] is not None:
        return "adversarial-fragment"
    if row["is_probe"]:
        return "probe"
    return "benign"


df["turn_type"] = df.apply(_turn_type, axis=1)

# -----------------------------------------------------------------
# Timeline chart — one bar per (session, turn_type) band
# -----------------------------------------------------------------
st.subheader("Session timeline")

color_scale = alt.Scale(
    domain=["benign", "adversarial-fragment", "trigger", "probe"],
    range=["#aaaaaa", "#f5a623", "#d0021b", "#4a90d9"],
)

agg = df.groupby(["session_id", "turn_type"]).size().reset_index(name="count")
chart = alt.Chart(agg).mark_bar().encode(
    x=alt.X("session_id:O", title="Session"),
    y=alt.Y("count:Q", title="Turn count"),
    color=alt.Color("turn_type:N", scale=color_scale, title="Turn type"),
    tooltip=["session_id", "turn_type", "count"],
).properties(height=320)
st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------------
# Session drill-down
# -----------------------------------------------------------------
st.subheader("Session detail")

sessions = sorted(df["session_id"].unique().tolist())
selected_session = st.selectbox("Select session", sessions)

session_df = df[df["session_id"] == selected_session][
    ["turn_id", "role", "turn_type", "content_hash", "fragment_id"]
]
st.dataframe(session_df, use_container_width=True, hide_index=True)
