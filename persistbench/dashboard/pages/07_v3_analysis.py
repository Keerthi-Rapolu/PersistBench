"""PersistBench — V3 Analysis
Consolidation Engine · Archive Layer · Semantic Persistence · Provenance DAG (§V3.1–V3.4)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import altair as alt
import pandas as pd
import streamlit as st
from persistbench.dashboard._theme import page_header, C
from persistbench.db.queries import (
    get_consolidation_summary,
    get_archive_summary,
    get_contamination_subgraph,
)

st.markdown("<title>PersistBench — V3 Analysis</title>", unsafe_allow_html=True)
page_header(
    "V3 Analysis",
    "Consolidation Engine · Archive Layer · Semantic Persistence · Provenance DAG (§V3.1–V3.4)",
)

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

# ── Run / Scenario selectors ──────────────────────────────────────
run_id = st.session_state.get("selected_run_id")
col_run, col_scen = st.columns([2, 2])
with col_run:
    if not run_id:
        runs = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()
        if not runs:
            st.warning("No runs in database.")
            st.stop()
        run_id = st.selectbox("Run", [r[0] for r in runs])

with col_scen:
    scenario_options = conn.execute(
        "SELECT DISTINCT scenario_id FROM sessions WHERE run_id=? ORDER BY scenario_id",
        [run_id],
    ).fetchall()
    scenario_ids = [r[0] for r in scenario_options]
    if not scenario_ids:
        st.warning("No scenarios for this run.")
        st.stop()
    scenario_id = st.selectbox("Scenario", scenario_ids, index=0)

# ── Check V3 data availability ────────────────────────────────────
v3_tables_exist = True
try:
    conn.execute("SELECT 1 FROM memory_summaries LIMIT 1")
    conn.execute("SELECT 1 FROM archived_memory_entries LIMIT 1")
except Exception:
    v3_tables_exist = False

if not v3_tables_exist:
    st.info(
        "V3 tables are not present in this database. "
        "Run the benchmark with `v3_consolidation=True` and `v3_archive=True` to populate them."
    )
    st.stop()

consol = get_consolidation_summary(conn, run_id, scenario_id)
archive = get_archive_summary(conn, run_id, scenario_id)

has_consolidation = consol["total_summaries"] > 0
has_archive = archive["total_archived"] > 0

if not has_consolidation and not has_archive:
    st.info(
        "No V3 consolidation or archive data found for this run/scenario. "
        "Re-run with `v3_consolidation=True` / `v3_archive=True` flags."
    )

# ══════════════════════════════════════════════════════════════════
# SECTION 1 — Consolidation Overview (V3.1)
# ══════════════════════════════════════════════════════════════════
st.markdown("### Consolidation Engine (§V3.1)")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Summaries", consol["total_summaries"])
m2.metric("Adversarial Summaries", consol["adversarial_summaries"])
m3.metric(
    "Adv. Rate",
    f"{consol['adversarial_summaries'] / consol['total_summaries']:.1%}"
    if consol["total_summaries"] > 0 else "—",
)
by_type = consol.get("by_type", {})
m4.metric("Summary Types", len(by_type))

if consol["total_summaries"] > 0:
    # Summary type breakdown bar chart
    type_df = pd.DataFrame(
        [{"type": k, "count": v} for k, v in by_type.items()]
    )
    type_chart = (
        alt.Chart(type_df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("type:N", title="Summary Type", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color(
                "type:N",
                scale=alt.Scale(
                    domain=["extractive", "abstractive", "latent"],
                    range=[C["benign"], C["probe"], C["adversarial"]],
                ),
                legend=alt.Legend(title="Type"),
            ),
            tooltip=["type:N", "count:Q"],
        )
        .properties(height=200, title="Summaries by Type")
    )
    st.altair_chart(type_chart, use_container_width=True)

    # Consolidation timeline
    summaries = consol["summaries"]
    if summaries:
        sdf = pd.DataFrame(summaries)
        sdf["color"] = sdf["is_adversarial"].map(
            {True: C["adversarial"], False: C["benign"]}
        )
        timeline_chart = (
            alt.Chart(sdf)
            .mark_circle(size=80, opacity=0.8)
            .encode(
                x=alt.X("created_session:Q", title="Session"),
                y=alt.Y("toxicity_score:Q", title="Toxicity Score", scale=alt.Scale(domain=[0, 1])),
                color=alt.Color(
                    "is_adversarial:N",
                    scale=alt.Scale(
                        domain=[True, False],
                        range=[C["adversarial"], C["benign"]],
                    ),
                    legend=alt.Legend(title="Adversarial"),
                ),
                shape=alt.Shape(
                    "summary_type:N",
                    scale=alt.Scale(
                        domain=["extractive", "abstractive", "latent"],
                        range=["circle", "square", "triangle"],
                    ),
                    legend=alt.Legend(title="Type"),
                ),
                tooltip=["summary_id:N", "summary_type:N", "created_session:Q",
                         "toxicity_score:Q", "source_count:Q", "is_adversarial:N"],
            )
            .properties(height=220, title="Consolidation Timeline — Toxicity by Session")
        )
        st.altair_chart(timeline_chart, use_container_width=True)

        with st.expander("Summary Records", expanded=False):
            disp = sdf[["summary_id", "summary_type", "created_session",
                         "toxicity_score", "source_count", "is_adversarial"]].copy()
            disp["summary_id"] = disp["summary_id"].str[:12] + "…"
            st.dataframe(disp, use_container_width=True, hide_index=True)
else:
    st.caption("No consolidation summaries recorded for this scenario.")

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 2 — Archive Layer (V3.2)
# ══════════════════════════════════════════════════════════════════
st.markdown("### Archive Layer (§V3.2)")

a1, a2, a3, a4 = st.columns(4)
a1.metric("Total Archived", archive["total_archived"])
a2.metric("Adversarial Archived", archive["adversarial_archived"])
a3.metric("Resurrection Events", archive["resurrection_count"])
a4.metric(
    "Adv. Resurrections",
    archive["adversarial_resurrections"],
    delta=None if archive["adversarial_resurrections"] == 0 else "⚠ FVS-6 risk",
    delta_color="inverse",
)

if archive["adversarial_resurrections"] > 0:
    st.warning(
        f"{archive['adversarial_resurrections']} adversarial archive resurrection(s) detected. "
        "This indicates that deleted adversarial content was re-accessed via semantic similarity "
        "(§V3.2, FVS-6). Review the entries below."
    )

if archive["total_archived"] > 0:
    adf = pd.DataFrame(archive["entries"])
    adf["color"] = adf["is_adversarial"].map(
        {True: C["adversarial"], False: C["dormant"]}
    )

    # Archive inventory scatter: session vs toxicity, size = resurrection_count
    inv_chart = (
        alt.Chart(adf)
        .mark_circle(opacity=0.85)
        .encode(
            x=alt.X("archived_session:Q", title="Archived at Session"),
            y=alt.Y("toxicity_score:Q", title="Toxicity Score", scale=alt.Scale(domain=[0, 1])),
            size=alt.Size(
                "resurrection_count:Q",
                scale=alt.Scale(range=[40, 300]),
                legend=alt.Legend(title="Resurrections"),
            ),
            color=alt.Color(
                "is_adversarial:N",
                scale=alt.Scale(domain=[True, False], range=[C["adversarial"], C["dormant"]]),
                legend=alt.Legend(title="Adversarial"),
            ),
            tooltip=["entry_id:N", "archived_session:Q", "archive_reason:N",
                     "toxicity_score:Q", "resurrection_count:Q", "is_adversarial:N"],
        )
        .properties(height=220, title="Archive Inventory — Toxicity & Resurrection Activity")
    )
    st.altair_chart(inv_chart, use_container_width=True)

    # Archive events table
    with st.expander("Archive Entries", expanded=False):
        disp_a = adf[["entry_id", "archived_session", "archive_reason",
                       "toxicity_score", "resurrection_count", "is_adversarial"]].copy()
        disp_a["entry_id"] = disp_a["entry_id"].str[:12] + "…"
        st.dataframe(disp_a, use_container_width=True, hide_index=True)

    # Resurrection events detail
    res_rows = conn.execute(
        """SELECT r.event_id, r.archive_id, r.query_session, r.similarity_score,
                  r.was_adversarial, r.resurrection_type
           FROM archive_resurrection_events r
           JOIN archived_memory_entries a ON a.archive_id = r.archive_id
           WHERE a.run_id = ? AND a.scenario_id = ?
           ORDER BY r.query_session""",
        [run_id, scenario_id],
    ).fetchall()

    if res_rows:
        st.markdown("**Resurrection Events**")
        rdf = pd.DataFrame(
            res_rows,
            columns=["event_id", "archive_id", "query_session",
                     "similarity_score", "was_adversarial", "resurrection_type"],
        )
        rdf["archive_id"] = rdf["archive_id"].str[:12] + "…"
        st.dataframe(rdf.drop(columns=["event_id"]), use_container_width=True, hide_index=True)
else:
    st.caption("No archived entries for this scenario.")

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 3 — Provenance DAG / Contamination Subgraph (V3.4)
# ══════════════════════════════════════════════════════════════════
st.markdown("### Provenance DAG — Contamination Subgraph (§V3.4)")

edges = get_contamination_subgraph(conn, run_id, scenario_id)

if edges:
    edf = pd.DataFrame(edges)

    # Edge table with adversarial highlighting
    with st.expander("Lineage Edges", expanded=True):
        disp_e = edf[["parent_id", "child_id", "lineage_type", "session_id",
                       "summary_type", "child_toxicity", "child_adversarial"]].copy()
        disp_e["parent_id"] = disp_e["parent_id"].str[:12] + "…"
        disp_e["child_id"]  = disp_e["child_id"].str[:12] + "…"
        st.dataframe(disp_e, use_container_width=True, hide_index=True)

    # Toxicity flow by session
    if "session_id" in edf.columns and "child_toxicity" in edf.columns:
        edf_valid = edf.dropna(subset=["child_toxicity"])
        if not edf_valid.empty:
            flow_chart = (
                alt.Chart(edf_valid)
                .mark_line(point=True)
                .encode(
                    x=alt.X("session_id:Q", title="Session"),
                    y=alt.Y("child_toxicity:Q", title="Child Toxicity",
                            scale=alt.Scale(domain=[0, 1])),
                    color=alt.Color(
                        "lineage_type:N",
                        legend=alt.Legend(title="Lineage Type"),
                    ),
                    tooltip=["session_id:Q", "lineage_type:N",
                             "summary_type:N", "child_toxicity:Q",
                             "child_adversarial:N"],
                )
                .properties(height=200, title="Toxicity Flow Through Lineage Edges")
            )
            st.altair_chart(flow_chart, use_container_width=True)

    # Adversarial edge fraction
    n_total = len(edf)
    n_adv = int(edf["child_adversarial"].sum()) if "child_adversarial" in edf.columns else 0
    col_e1, col_e2, col_e3 = st.columns(3)
    col_e1.metric("Total Lineage Edges", n_total)
    col_e2.metric("Adversarial Child Edges", n_adv)
    col_e3.metric(
        "Contamination Rate",
        f"{n_adv / n_total:.1%}" if n_total > 0 else "—",
    )
    if n_adv > 0:
        st.warning(
            f"{n_adv} lineage edge(s) carry adversarial child summaries. "
            "This indicates that deleted adversarial content influenced at least one derived summary "
            "(§V3.4, FVS-7/FVS-8). Run `get_descendant_chain()` per entry for full impact analysis."
        )
else:
    st.caption("No summary lineage edges recorded for this scenario.")

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 4 — Semantic Persistence Metrics (V3.3)
# ══════════════════════════════════════════════════════════════════
st.markdown("### Semantic Persistence (§V3.3, FVS-9 & FVS-10)")

fvs_rows = conn.execute(
    """SELECT fvs_test_id, passed, failure_reason, pathway, created_at
       FROM forgetting_validation
       WHERE run_id = ? AND scenario_id = ?
         AND fvs_test_id IN ('FVS-9', 'FVS-10')
       ORDER BY created_at""",
    [run_id, scenario_id],
).fetchall()

if fvs_rows:
    fdf = pd.DataFrame(
        fvs_rows, columns=["fvs_test_id", "passed", "failure_reason", "pathway", "created_at"]
    )
    fdf_9  = fdf[fdf["fvs_test_id"] == "FVS-9"]
    fdf_10 = fdf[fdf["fvs_test_id"] == "FVS-10"]

    col_f9, col_f10 = st.columns(2)
    with col_f9:
        n9 = len(fdf_9)
        p9 = int(fdf_9["passed"].sum()) if n9 > 0 else 0
        st.markdown(
            f"<div class='pb-card' style='border-left:4px solid {C['probe']};'>"
            f"<div class='pb-card-title'>FVS-9 — Semantic Neighbor Recall</div>"
            f"<div style='font-size:1.3rem;font-weight:700;'>{p9}/{n9} passed</div>"
            f"<p style='font-size:0.82rem;color:#6C757D;margin-top:4px;'>"
            f"Deleted entry must not resurface in top-K semantic neighbors above "
            f"similarity threshold {0.85}. Tests probe post-deletion Qdrant recall."
            f"</p></div>",
            unsafe_allow_html=True,
        )
    with col_f10:
        n10 = len(fdf_10)
        p10 = int(fdf_10["passed"].sum()) if n10 > 0 else 0
        st.markdown(
            f"<div class='pb-card' style='border-left:4px solid {C['probe']};'>"
            f"<div class='pb-card-title'>FVS-10 — Latent Embedding Ghost</div>"
            f"<div style='font-size:1.3rem;font-weight:700;'>{p10}/{n10} passed</div>"
            f"<p style='font-size:0.82rem;color:#6C757D;margin-top:4px;'>"
            f"Deleted embedding must not be latently reconstructable from surviving neighbors "
            f"via least-squares (threshold: reconstruction error &gt; 0.15)."
            f"</p></div>",
            unsafe_allow_html=True,
        )

    with st.expander("FVS-9 / FVS-10 Details", expanded=False):
        st.dataframe(
            fdf[["fvs_test_id", "passed", "pathway", "failure_reason"]],
            use_container_width=True,
            hide_index=True,
        )
else:
    st.caption(
        "No FVS-9 or FVS-10 results for this scenario. "
        "These tests require Qdrant to be configured and run with `v3_consolidation=True`."
    )

# FVS-6 through FVS-8 summary (consolidation / archive pathway)
fvs_v3_rows = conn.execute(
    """SELECT fvs_test_id, passed, failure_reason, pathway, created_at
       FROM forgetting_validation
       WHERE run_id = ? AND scenario_id = ?
         AND fvs_test_id IN ('FVS-6', 'FVS-7', 'FVS-8')
       ORDER BY fvs_test_id, created_at""",
    [run_id, scenario_id],
).fetchall()

if fvs_v3_rows:
    st.markdown("**FVS-6 / FVS-7 / FVS-8 — Consolidation & Archive Pathways**")
    v3df = pd.DataFrame(
        fvs_v3_rows,
        columns=["fvs_test_id", "passed", "failure_reason", "pathway", "created_at"],
    )
    summary_rows = (
        v3df.groupby("fvs_test_id")
        .agg(passed=("passed", "sum"), total=("passed", "count"))
        .reset_index()
    )
    summary_rows["rate"] = summary_rows.apply(
        lambda r: f"{r['passed']}/{r['total']}", axis=1
    )

    fvs_bar = (
        alt.Chart(summary_rows)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("fvs_test_id:N", title="FVS Test", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("passed:Q", title="Tests Passed"),
            color=alt.Color(
                "fvs_test_id:N",
                scale=alt.Scale(
                    domain=["FVS-6", "FVS-7", "FVS-8"],
                    range=[C["probe"], C["quarantine"], C["adversarial"]],
                ),
                legend=None,
            ),
            tooltip=["fvs_test_id:N", "passed:Q", "total:Q"],
        )
        .properties(height=180, title="FVS-6–8 Pass Count by Test")
    )
    st.altair_chart(fvs_bar, use_container_width=True)

    with st.expander("FVS-6–8 Details", expanded=False):
        st.dataframe(
            v3df[["fvs_test_id", "passed", "pathway", "failure_reason"]],
            use_container_width=True,
            hide_index=True,
        )
