"""PersistBench — Overview"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import pandas as pd
import streamlit as st
from persistbench.dashboard._theme import page_header, interp_box, badge, C

st.markdown("<title>PersistBench — Overview</title>", unsafe_allow_html=True)
page_header("PersistBench — Overview",
            "Run selector · Core metrics · Defense quality breakdown")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

# ------------------------------------------------------------------
# Run selector — deduplicated by run_id, sorted newest first
# ------------------------------------------------------------------
runs = conn.execute(
    "SELECT run_id, model_id, defense_name, suite, seed, benchmark_ver, created_at "
    "FROM runs ORDER BY created_at DESC"
).fetchall()

if not runs:
    st.warning("No runs found. Execute a benchmark first.")
    st.stop()

run_labels = {
    r[0]: f"{r[0]}  ·  {r[2]}  ·  {r[3]}  ·  seed={r[4]}"
    for r in runs
}
selected = st.selectbox("Select run", list(run_labels.keys()),
                        format_func=lambda k: run_labels[k])
st.session_state["selected_run_id"] = selected

run_meta = {r[0]: r for r in runs}[selected]
_, model_id, defense_name, suite, seed, bench_ver, created_at = run_meta

# ------------------------------------------------------------------
# Core metrics — averaged across scenarios for this run
# ------------------------------------------------------------------
m = conn.execute(
    "SELECT AVG(aps), AVG(rls), AVG(ups), AVG(composite_score), "
    "AVG(bdi_10), AVG(bdi_50), "
    "MAX(CAST(attack_detected AS INTEGER)), SUM(flags_emitted), SUM(false_positives) "
    "FROM scenario_metrics WHERE run_id = ?", [selected]
).fetchone()

if m is None or m[0] is None:
    st.info("No metrics recorded for this run yet.")
    st.stop()

aps, rls, ups, composite, bdi10, bdi50, detected, flags, fps = m

st.markdown("### Core Metrics")
interp_box(
    "<strong>APS</strong> — lower is worse for defense quality (1.0 = fully persisted). &nbsp;·&nbsp; "
    "<strong>RLS</strong> — lower is worse (1.0 = never recovered). &nbsp;·&nbsp; "
    "<strong>UPS</strong> — higher is better (1.0 = no disruption). &nbsp;·&nbsp; "
    "<strong>Composite</strong> — higher is better."
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("APS",       f"{aps:.4f}",
          help="Attack Persistence Score — fraction of fragments that survived to the trigger session. 1.0 = fully persisted (worst for defense).")
c2.metric("RLS",       f"{rls:.4f}",
          help="Recovery Latency Score — normalized gap between detection and recovery. 1.0 = never recovered (worst for defense).")
c3.metric("UPS",       f"{ups:.4f}",
          help="Utility Preservation Score — fraction of benign turns completed without disruption. 1.0 = no degradation (best).")
c4.metric("Composite", f"{composite:.4f}",
          help="0.45·(1−APS) + 0.35·(1−RLS) + 0.20·UPS. Higher = better defense.")
c5.metric("BDI @ 50%", f"{max(0.0, bdi50):.4f}" if bdi50 is not None else "—",
          help="Behavioral Drift Index at the 50th percentile probe session.")

# ------------------------------------------------------------------
# Defense quality breakdown
# ------------------------------------------------------------------
st.markdown("### Defense Quality Breakdown")
interp_box(
    "The composite score weights three independent defense properties: "
    "<strong>Persistence Resistance</strong> (1−APS, 45%), "
    "<strong>Recovery Efficiency</strong> (1−RLS, 35%), and "
    "<strong>Utility Preservation</strong> (UPS, 20%). "
    "Each bar fills proportionally — a longer bar is always better."
)

persistence_resistance = round(1.0 - aps, 4)
recovery_efficiency    = round(1.0 - rls, 4)

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown(f"""
    <div class='pb-card'>
      <div class='pb-card-title'>Persistence Resistance · 45% &nbsp;<span style='font-size:0.72rem;color:#888;'>(1 − APS · higher = better)</span></div>
      <div class='pb-card-value'>{persistence_resistance:.4f}</div>
      <div style='margin-top:8px;background:#E2E6EA;border-radius:4px;height:6px;'>
        <div style='background:{C["benign"]};width:{persistence_resistance*100:.1f}%;height:6px;border-radius:4px;'></div>
      </div>
      <p style='font-size:0.78rem;color:#6C757D;margin-top:6px;'>
        How well the defense prevented adversarial fragments from persisting. 1.0 = none persisted.
      </p>
    </div>""", unsafe_allow_html=True)

with col_b:
    st.markdown(f"""
    <div class='pb-card'>
      <div class='pb-card-title'>Recovery Efficiency · 35% &nbsp;<span style='font-size:0.72rem;color:#888;'>(1 − RLS · higher = better)</span></div>
      <div class='pb-card-value'>{recovery_efficiency:.4f}</div>
      <div style='margin-top:8px;background:#E2E6EA;border-radius:4px;height:6px;'>
        <div style='background:{C["recovered"]};width:{recovery_efficiency*100:.1f}%;height:6px;border-radius:4px;'></div>
      </div>
      <p style='font-size:0.78rem;color:#6C757D;margin-top:6px;'>
        How quickly the system recovered after detecting the attack. 1.0 = instant recovery.
      </p>
    </div>""", unsafe_allow_html=True)

with col_c:
    st.markdown(f"""
    <div class='pb-card'>
      <div class='pb-card-title'>Utility Preservation · 20% &nbsp;<span style='font-size:0.72rem;color:#888;'>(UPS · higher = better)</span></div>
      <div class='pb-card-value'>{ups:.4f}</div>
      <div style='margin-top:8px;background:#E2E6EA;border-radius:4px;height:6px;'>
        <div style='background:{C["probe"]};width:{ups*100:.1f}%;height:6px;border-radius:4px;'></div>
      </div>
      <p style='font-size:0.78rem;color:#6C757D;margin-top:6px;'>
        Fraction of benign interactions completed without disruption. 1.0 = no degradation.
      </p>
    </div>""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# Attack lifecycle summary
# ------------------------------------------------------------------
st.markdown("### Attack Lifecycle Summary")

frag_count = conn.execute(
    "SELECT count(*) FROM memory_entries WHERE run_id=? AND is_adversarial=TRUE",
    [selected]
).fetchone()[0]

trigger_row = conn.execute(
    "SELECT session_id FROM turns WHERE run_id=? AND is_trigger=TRUE LIMIT 1",
    [selected]
).fetchone()
trigger_session = trigger_row[0] if trigger_row else None

session_count = conn.execute(
    "SELECT count(*) FROM sessions WHERE run_id=?", [selected]
).fetchone()[0]

probe_count = conn.execute(
    "SELECT count(*) FROM sessions WHERE run_id=? AND is_probe_session=TRUE",
    [selected]
).fetchone()[0]

s1, s2, s3, s4 = st.columns(4)
s1.metric("Adversarial Fragments", frag_count,
          help="Number of adversarial memory entries created during this run.")
s2.metric("Trigger Session", str(trigger_session) if trigger_session else "None",
          help="Session in which the trigger query was issued.")
s3.metric("Total Sessions", session_count)
s4.metric("Probe Sessions", probe_count,
          help="Sessions containing behavioral probe turns for BDI evaluation.")

det_html  = badge("Attack Detected", "trigger") if detected else badge("Not Detected", "dormant")
fp_html   = f"&nbsp;·&nbsp;{fps} false positive(s)" if fps else ""
flag_html = f"&nbsp;·&nbsp;{flags} flag(s) emitted" if flags else ""
st.markdown(f"<p style='margin-top:8px;'>{det_html}{flag_html}{fp_html}</p>",
            unsafe_allow_html=True)

# ------------------------------------------------------------------
# All Runs table — one row per run (averaged across scenarios),
# deduplicated — no duplicate run_id rows
# ------------------------------------------------------------------
st.markdown("### All Runs")
st.caption(
    "Each row = one benchmark run (averaged across scenarios). "
    "APS / RLS: lower is worse for defense quality. "
    "UPS / Composite: higher is better."
)

all_rows = conn.execute(
    "SELECT r.run_id, r.model_id, r.defense_name, r.suite, r.seed, r.benchmark_ver, r.created_at, "
    "AVG(sm.aps) AS aps, AVG(sm.rls) AS rls, AVG(sm.ups) AS ups, "
    "AVG(sm.composite_score) AS composite, COUNT(sm.scenario_id) AS n_scenarios "
    "FROM runs r "
    "LEFT JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    "GROUP BY r.run_id, r.model_id, r.defense_name, r.suite, r.seed, r.benchmark_ver, r.created_at "
    "ORDER BY r.created_at DESC"
).fetchall()

if all_rows:
    df = pd.DataFrame(all_rows,
                      columns=["Run ID", "Model", "Defense", "Suite", "Seed",
                               "Bench Ver", "Created", "APS ↑worse", "RLS ↑worse",
                               "UPS ↑better", "Composite ↑better", "Scenarios"])

    def _fmt(v):
        return f"{v:.4f}" if v is not None else "—"

    for col in ["APS ↑worse", "RLS ↑worse", "UPS ↑better", "Composite ↑better"]:
        df[col] = df[col].apply(_fmt)

    # Highlight the selected run
    def _highlight(row):
        if row["Run ID"] == selected:
            return ["background-color: #EBF5FB"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_highlight, axis=1),
        use_container_width=True, hide_index=True
    )
