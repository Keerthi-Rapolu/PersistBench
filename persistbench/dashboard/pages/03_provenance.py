"""Provenance Lineage — tamper-evident chain as a DAG."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

st.title("Provenance Lineage")

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
# Fetch provenance events
# -----------------------------------------------------------------
rows = conn.execute(
    "SELECT event_id, entry_id, event_type, session_id, chain_hash "
    "FROM provenance_events WHERE run_id = ? ORDER BY created_at",
    [run_id],
).fetchall()

if not rows:
    st.info("No provenance events for this run.")
    st.stop()

# -----------------------------------------------------------------
# Build PyVis graph
# -----------------------------------------------------------------
net = Network(height="500px", width="100%", directed=True,
              bgcolor="#ffffff", font_color="#222222")
net.set_options("""
{
  "physics": {"enabled": false},
  "edges": {"arrows": {"to": {"enabled": true}}},
  "nodes": {"font": {"size": 12}}
}
""")

lifecycle_colors = {
    "created": "#f5a623",
    "reinforced": "#7ed321",
    "deleted": "#d0021b",
    "accessed": "#4a90d9",
}

added_entries = set()
prev_node = None

for event_id, entry_id, event_type, session_id, chain_hash in rows:
    node_id = entry_id
    short_hash = chain_hash[:18] if chain_hash else "?"
    color = lifecycle_colors.get(event_type, "#aaaaaa")

    if node_id not in added_entries:
        net.add_node(
            node_id,
            label=entry_id,
            title=f"entry: {entry_id}\nevent: {event_type}\nsession: {session_id}\nhash: {short_hash}",
            color=color,
        )
        added_entries.add(node_id)

    if prev_node and prev_node != node_id:
        net.add_edge(prev_node, node_id,
                     title=f"event_id: {event_id[:8]}...\nhash: {short_hash}")
    prev_node = node_id

html = net.generate_html()
components.html(html, height=520, scrolling=False)

# -----------------------------------------------------------------
# Event table
# -----------------------------------------------------------------
st.subheader("Provenance events")
import pandas as pd
df = pd.DataFrame(rows, columns=["event_id", "entry_id", "event_type",
                                  "session_id", "chain_hash"])
df["chain_hash"] = df["chain_hash"].str[:20] + "..."
st.dataframe(df, use_container_width=True, hide_index=True)
