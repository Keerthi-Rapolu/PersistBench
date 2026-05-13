"""Persistence Evolution — APS evolution, contamination timeline, recovery heatmap."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

st.title("Persistence Evolution")

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
# 1. APS evolution over sessions
# Proxy: fraction of adversarial memory entries visible by each session
# -----------------------------------------------------------------
st.subheader("APS evolution over sessions")

frag_rows = conn.execute(
    "SELECT created_session FROM memory_entries "
    "WHERE run_id = ? AND is_adversarial = TRUE ORDER BY created_session",
    [run_id],
).fetchall()

total_sessions = conn.execute(
    "SELECT count(*) FROM sessions WHERE run_id = ?", [run_id]
).fetchone()[0]

if frag_rows and total_sessions:
    total_frags = len(frag_rows)
    planted_by = {}
    for (sess,) in frag_rows:
        planted_by[sess] = planted_by.get(sess, 0) + 1

    cumulative = 0
    aps_rows = []
    for sid in range(1, total_sessions + 1):
        cumulative += planted_by.get(sid, 0)
        aps_rows.append({"session": sid, "aps": round(cumulative / total_frags, 4)})

    df_aps = pd.DataFrame(aps_rows)
    chart = alt.Chart(df_aps).mark_line(point=True).encode(
        x=alt.X("session:Q", title="Session"),
        y=alt.Y("aps:Q", title="APS (fraction persisted)", scale=alt.Scale(domain=[0, 1])),
        tooltip=["session", "aps"],
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No adversarial memory entries found for this run.")

# -----------------------------------------------------------------
# 2. Contamination timeline
# -----------------------------------------------------------------
st.subheader("Contamination timeline")

sess_rows = conn.execute(
    "SELECT s.session_id, s.is_attack_session, s.is_trigger_session, "
    "s.is_probe_session, s.turn_count "
    "FROM sessions s WHERE s.run_id = ? ORDER BY s.session_id",
    [run_id],
).fetchall()

if sess_rows:
    timeline_data = []
    for sid, is_atk, is_trig, is_probe, tc in sess_rows:
        if is_trig:
            state = "trigger"
        elif is_atk:
            state = "fragment-planted"
        elif is_probe:
            state = "probe"
        else:
            state = "clean"
        timeline_data.append({"session": sid, "state": state, "turns": tc})

    df_tl = pd.DataFrame(timeline_data)
    color_scale = alt.Scale(
        domain=["clean", "fragment-planted", "trigger", "probe"],
        range=["#aaaaaa", "#f5a623", "#d0021b", "#4a90d9"],
    )
    chart_tl = alt.Chart(df_tl).mark_bar().encode(
        x=alt.X("session:O", title="Session"),
        y=alt.Y("turns:Q", title="Turns"),
        color=alt.Color("state:N", scale=color_scale, title="Session type"),
        tooltip=["session", "state", "turns"],
    ).properties(height=300)
    st.altair_chart(chart_tl, use_container_width=True)

# -----------------------------------------------------------------
# 3. Recovery latency (single run — show metric cards instead of heatmap)
# -----------------------------------------------------------------
st.subheader("Recovery latency")
rls_row = conn.execute(
    "SELECT rls, detection_session, recovery_session "
    "FROM scenario_metrics WHERE run_id = ?",
    [run_id],
).fetchone()

if rls_row:
    rls, det, rec = rls_row
    c1, c2, c3 = st.columns(3)
    c1.metric("RLS", f"{rls:.4f}")
    c2.metric("Detection session", str(det) if det else "—")
    c3.metric("Recovery session", str(rec) if rec else "—")
    if det is None:
        st.info("Attack was not detected (no defense active or defense missed it).")
