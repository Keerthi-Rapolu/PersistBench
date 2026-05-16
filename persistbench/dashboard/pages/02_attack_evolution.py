"""PersistBench — Attack Evolution
Flagship page: longitudinal hero chart + session timeline + APS/BDI curves.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import altair as alt
import pandas as pd
import streamlit as st
from persistbench.dashboard._theme import page_header, interp_box, C

st.markdown("<title>PersistBench — Attack Evolution</title>", unsafe_allow_html=True)
page_header("Attack Evolution",
            "Longitudinal lifecycle · Persistence curve · Behavioral drift · Session drill-down")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

run_id = st.session_state.get("selected_run_id")
col_run, col_scen = st.columns([2, 2])
with col_run:
    if not run_id:
        runs = conn.execute(
            "SELECT DISTINCT r.run_id FROM runs r ORDER BY r.created_at DESC"
        ).fetchall()
        if not runs:
            st.warning("No runs in database.")
            st.stop()
        run_id = st.selectbox("Run", [r[0] for r in runs])

with col_scen:
    scenario_options = conn.execute(
        "SELECT DISTINCT scenario_id FROM sessions WHERE run_id=? "
        "ORDER BY scenario_id", [run_id]
    ).fetchall()
    scenario_ids = [r[0] for r in scenario_options]
    if not scenario_ids:
        st.warning("No scenarios for this run.")
        st.stop()
    scenario_id = st.selectbox("Scenario", scenario_ids, index=0)

# ------------------------------------------------------------------
# Data — gathered once, shared across all tabs (filtered by scenario)
# ------------------------------------------------------------------
turn_rows = conn.execute(
    "SELECT session_id, turn_id, role, content_hash, is_benign, is_trigger, is_probe, fragment_id "
    "FROM turns WHERE run_id=? AND scenario_id=? ORDER BY session_id, turn_id",
    [run_id, scenario_id]
).fetchall()

session_rows = conn.execute(
    "SELECT session_id, bdi_value, is_probe_session, is_attack_session, is_trigger_session "
    "FROM sessions WHERE run_id=? AND scenario_id=? ORDER BY session_id",
    [run_id, scenario_id]
).fetchall()

frag_rows = conn.execute(
    "SELECT entry_id, created_session FROM memory_entries "
    "WHERE run_id=? AND scenario_id=? AND is_adversarial=TRUE "
    "AND (lifecycle_stage IS NULL OR lifecycle_stage != 'blocked')",
    [run_id, scenario_id]
).fetchall()

# All adversarial entries (including blocked) — used as denominator so blocked
# fragments don't inflate the survival fraction (APS = persisted / total_intended).
_all_adv_count = conn.execute(
    "SELECT COUNT(*) FROM memory_entries "
    "WHERE run_id=? AND scenario_id=? AND is_adversarial=TRUE",
    [run_id, scenario_id]
).fetchone()[0]

snap_rows = conn.execute(
    "SELECT entry_id, session_id, trust_score, toxicity_score "
    "FROM memory_entry_snapshots WHERE run_id=? AND scenario_id=? ORDER BY session_id",
    [run_id, scenario_id]
).fetchall()

if not turn_rows:
    st.info("No turn data for this run.")
    st.stop()

tdf = pd.DataFrame(turn_rows,
                   columns=["session_id","turn_id","role","content_hash",
                             "is_benign","is_trigger","is_probe","fragment_id"])
sdf = pd.DataFrame(session_rows,
                   columns=["session_id","bdi_value","is_probe","is_attack","is_trigger_sess"])

frag_planted: dict[int, int] = {}
for _, cs in frag_rows:
    frag_planted[cs] = frag_planted.get(cs, 0) + 1

# Use total adversarial count (including blocked) as denominator so the survival
# fraction reflects APS correctly: persisted / total_intended, not persisted / persisted.
total_frags_denom = _all_adv_count if _all_adv_count > 0 else len(frag_rows)

trigger_rows_t = tdf[tdf["is_trigger"] == True]
trigger_session = int(trigger_rows_t["session_id"].iloc[0]) if len(trigger_rows_t) else None
frag_sessions   = sorted(set(tdf[tdf["fragment_id"].notna()]["session_id"].tolist()))
first_frag      = frag_sessions[0] if frag_sessions else None
last_frag       = frag_sessions[-1] if frag_sessions else None
all_sessions    = sorted(sdf["session_id"].unique().tolist())

def _phase(sid):
    if sid == trigger_session:                                              return "Activation"
    if frag_sessions and sid in frag_sessions:                             return "Seeding"
    if last_frag and trigger_session and last_frag < sid < trigger_session: return "Dormant"
    if first_frag and sid < first_frag:                                    return "Clean"
    if trigger_session and sid > trigger_session:                          return "Post-Activation"
    return "Clean"

sdf["phase"] = sdf["session_id"].apply(_phase)
phase_colors = {
    "Clean": C["benign"], "Seeding": C["adversarial"],
    "Dormant": C["dormant"], "Activation": C["trigger"], "Post-Activation": C["probe"],
}

# Phase bands (shared between tabs)
phase_bands = []
prev_phase  = sdf.iloc[0]["phase"]
band_start  = sdf.iloc[0]["session_id"]
for _, row in sdf.iterrows():
    if row["phase"] != prev_phase:
        phase_bands.append({"phase": prev_phase, "x1": band_start - 0.5,
                             "x2": row["session_id"] - 0.5})
        band_start = row["session_id"]
        prev_phase = row["phase"]
phase_bands.append({"phase": prev_phase, "x1": band_start - 0.5,
                    "x2": all_sessions[-1] + 0.5})

# Turn type classification — canonical, used in Tab 2
def _turn_type(row) -> str:
    """Classify a turn using reliable source fields in priority order.

    Priority: trigger > probe > adversarial > benign.
    Uses pd.notna() for fragment_id because DuckDB NULLs become NaN (float),
    not None — so `is not None` would misclassify clean turns as adversarial.
    Uses == False (not `is False`) so numpy.bool_ works correctly.
    """
    if row["is_trigger"]:
        return "trigger"
    if row["is_probe"]:
        return "probe"
    if pd.notna(row["fragment_id"]) and row["fragment_id"] != "":
        return "adversarial"
    if row["is_benign"] == False:   # noqa: E712 — intentional: handles numpy.bool_
        return "adversarial"
    return "benign"

tab1, tab2, tab3 = st.tabs(["🎯 Longitudinal View", "⏱ Session Timeline", "📈 APS + BDI Curves"])

# ==================================================================
# TAB 1 — Longitudinal hero chart
# ==================================================================
with tab1:
    interp_box(
        "Orange fill = fraction of adversarial fragments accumulated in memory. "
        "Green dashed lines = per-fragment trust decay. "
        "Red dashed = BDI at probe sessions. Solid red line = trigger activation."
    )

    bg_scale  = alt.Scale(domain=list(phase_colors.keys()), range=list(phase_colors.values()))
    band_df   = pd.DataFrame(phase_bands)
    domain    = [all_sessions[0] - 0.5, all_sessions[-1] + 0.5]

    bg_layer = alt.Chart(band_df).mark_rect(opacity=0.14).encode(
        x=alt.X("x1:Q", scale=alt.Scale(domain=domain), axis=None),
        x2="x2:Q", y=alt.value(0), y2=alt.value(1),
        color=alt.Color("phase:N", scale=bg_scale, legend=alt.Legend(
            title="Phase", orient="bottom", direction="horizontal",
            symbolType="square", labelFontSize=10)),
    )

    # Cumulative fragment fraction
    cumulative = 0
    cum_rows   = []
    for sid in all_sessions:
        cumulative += frag_planted.get(sid, 0)
        cum_rows.append({"session_id": sid, "frag_frac": round(cumulative / total_frags_denom, 4)
                         if total_frags_denom else 0.0})
    cum_df = pd.DataFrame(cum_rows)

    frag_area = alt.Chart(cum_df).mark_area(
        color=C["adversarial"], opacity=0.20, interpolate="step-after"
    ).encode(
        x=alt.X("session_id:Q", axis=None),
        y=alt.Y("frag_frac:Q", title="Fragment Survival Fraction",
                scale=alt.Scale(domain=[0, 1])),
    )
    frag_line = alt.Chart(cum_df).mark_line(
        color=C["adversarial"], strokeWidth=2.0, interpolate="step-after"
    ).encode(
        x="session_id:Q",
        y=alt.Y("frag_frac:Q"),
        tooltip=[
            alt.Tooltip("session_id:Q", title="Session"),
            alt.Tooltip("frag_frac:Q", title="Fragment Survival Fraction", format=".3f"),
        ]
    )

    # BDI line at probe sessions
    probe_df = sdf[sdf["is_probe"] == True].dropna(subset=["bdi_value"])
    bdi_line = alt.Chart(probe_df).mark_line(
        color=C["trigger"], strokeWidth=2.5, strokeDash=[4, 2], interpolate="monotone"
    ).encode(
        x="session_id:Q",
        y=alt.Y("bdi_value:Q"),
        tooltip=[
            alt.Tooltip("session_id:Q", title="Session"),
            alt.Tooltip("bdi_value:Q", title="BDI", format=".3f"),
        ]
    )
    bdi_pts = alt.Chart(probe_df).mark_circle(color=C["trigger"], size=80).encode(
        x="session_id:Q", y="bdi_value:Q")

    # Trust lines from snapshots
    trust_layers = []
    if snap_rows:
        snap_df = pd.DataFrame(snap_rows,
                               columns=["entry_id","session_id","trust_score","toxicity_score"])
        for eid in snap_df["entry_id"].unique():
            edf = snap_df[snap_df["entry_id"] == eid].sort_values("session_id")
            trust_layers.append(
                alt.Chart(edf).mark_line(strokeWidth=1.5, opacity=0.65, strokeDash=[2, 1]
                ).encode(
                    x="session_id:Q",
                    y=alt.Y("trust_score:Q"),
                    color=alt.value(C["recovered"]),
                    tooltip=[
                        alt.Tooltip("entry_id:N", title="Fragment"),
                        alt.Tooltip("session_id:Q", title="Session"),
                        alt.Tooltip("trust_score:Q", title="Trust Score", format=".3f"),
                    ]
                ))

    # Markers
    marker_layers = []
    for fs in frag_sessions:
        marker_layers.append(
            alt.Chart(pd.DataFrame([{"x": fs}])).mark_rule(
                color=C["adversarial"], strokeWidth=1.2, strokeDash=[3, 2]
            ).encode(x="x:Q"))
    if trigger_session:
        marker_layers += [
            alt.Chart(pd.DataFrame([{"x": trigger_session}])).mark_rule(
                color=C["trigger"], strokeWidth=4
            ).encode(x="x:Q"),
            alt.Chart(pd.DataFrame([{"x": trigger_session, "y": 0.92,
                                     "t": "▼ TRIGGER ACTIVATED"}])
            ).mark_text(align="left", dx=6, fontSize=11,
                        fontWeight="bold", color=C["trigger"]
            ).encode(x="x:Q", y="y:Q", text="t:N", tooltip=alt.value(None)),
        ]

    # Phase labels — use full names, not truncated
    label_rows = [{"x": (b["x1"]+b["x2"])/2, "y": 0.96, "label": b["phase"]}
                  for b in phase_bands]
    phase_labels = alt.Chart(pd.DataFrame(label_rows)).mark_text(
        fontSize=10, fontStyle="italic", fontWeight="bold", opacity=0.80,
        dy=-4, align="center",
    ).encode(x="x:Q", y="y:Q", text="label:N",
             color=alt.Color("label:N", scale=bg_scale, legend=None),
             tooltip=alt.value(None))

    all_layers = ([bg_layer, frag_area, frag_line] + trust_layers +
                  marker_layers + [bdi_line, bdi_pts, phase_labels])
    hero = alt.layer(*all_layers).encode(
        x=alt.X(scale=alt.Scale(domain=domain),
                axis=alt.Axis(title="Session", tickMinStep=1, labelFontSize=11,
                              format="d", labelOverlap=False))
    ).properties(
        height=420,
        title=alt.TitleParams(
            text=f"Longitudinal Attack Evolution — {run_id}",
            subtitle=(
                "Orange fill = adversarial fragments in memory  ·  "
                "Red dashed = BDI (probe sessions)  ·  "
                "Green dashed = trust scores per fragment  ·  "
                "Solid red = trigger activation"
            ),
            fontSize=14, subtitleFontSize=11,
            color="#2C3E50", subtitleColor="#6C757D",
        )
    ).resolve_scale(y="shared")
    st.altair_chart(hero, use_container_width=True)

    # Phase narrative cards
    st.markdown("#### Attack Lifecycle Narrative")
    narratives = {
        "Clean":           ("Benign baseline. Agent has no adversarial memory. "
                            "Probe sessions confirm clean behavior (BDI = 0.0).", "benign"),
        "Seeding":         ("Adversarial fragments silently inserted into agent memory. "
                            "Agent behaves normally — contamination is invisible.", "adversarial"),
        "Dormant":         ("All fragments planted. Attack persists undetected across sessions. "
                            "Trust decays slowly. This phase shows benchmark diagnostic depth.", "dormant"),
        "Activation":      ("Trigger query fires. Accumulated adversarial context activates. "
                            "BDI spikes. The attack succeeds.", "trigger"),
        "Post-Activation": ("Behavior post-trigger. Probes measure residual contamination. "
                            "Recovery requires defense intervention.", "probe"),
    }
    seen_phases, phase_seq = set(), []
    for band in phase_bands:
        if band["phase"] not in seen_phases:
            phase_seq.append(band); seen_phases.add(band["phase"])

    cols = st.columns(len(phase_seq))
    for col, band in zip(cols, phase_seq):
        ph = band["phase"]
        text, _ = narratives.get(ph, (ph, "neutral"))
        color = phase_colors.get(ph, C["neutral"])
        s_range = f"S{band['x1']+0.5:.0f}–S{band['x2']-0.5:.0f}"
        with col:
            st.markdown(
                f"<div style='border-left:4px solid {color};padding:10px 12px;"
                f"background:{color}11;border-radius:0 6px 6px 0;'>"
                f"<div style='font-size:0.68rem;color:#6C757D;text-transform:uppercase;"
                f"letter-spacing:.06em;margin-bottom:2px;'>{s_range}</div>"
                f"<div style='font-weight:600;color:{color};margin-bottom:4px;'>{ph}</div>"
                f"<div style='font-size:0.78rem;color:#34495E;line-height:1.5;'>{text}</div>"
                f"</div>", unsafe_allow_html=True)

# ==================================================================
# TAB 2 — Session-level timeline + drill-down
# ==================================================================
with tab2:
    interp_box(
        "Stacked bars show turn composition per session. "
        "Benign = clean turns · Adversarial = fragment injections · "
        "Trigger = trigger query turn · Probe = safety probe turns. "
        "Background shading shows attack phase."
    )

    tdf["turn_type"] = tdf.apply(_turn_type, axis=1)

    sess_agg = (tdf.groupby("session_id")["turn_type"]
                .value_counts().unstack(fill_value=0).reset_index())
    for col in ["benign", "adversarial", "trigger", "probe"]:
        if col not in sess_agg.columns:
            sess_agg[col] = 0
    sess_agg["phase"] = sess_agg["session_id"].apply(_phase)

    type_order   = ["benign", "adversarial", "trigger", "probe"]
    type_display = ["Benign", "Adversarial", "Trigger", "Probe"]
    type_colors  = [C["benign"], C["adversarial"], C["trigger"], C["probe"]]

    # Rename columns for display
    sess_display = sess_agg.copy()
    for raw, nice in zip(type_order, type_display):
        if raw in sess_display.columns:
            sess_display[nice] = sess_display[raw]

    melted = sess_agg.melt(id_vars=["session_id","phase"],
                           value_vars=type_order, var_name="turn_type", value_name="count")
    # Map raw names to display names for legend
    melted["Turn Type"] = melted["turn_type"].map(
        dict(zip(type_order, type_display)))
    melted = melted[melted["count"] > 0]

    # Phase background — use same ordinal scale as bars (avoids Q/O axis bleed)
    sess_phase_df = pd.DataFrame([
        {"session_id": sid, "phase": _phase(sid)} for sid in all_sessions
    ])
    bg2 = alt.Chart(sess_phase_df).mark_rect(opacity=0.12).encode(
        x=alt.X("session_id:O", axis=None),
        color=alt.Color("phase:N",
                        scale=alt.Scale(domain=list(phase_colors.keys()),
                                        range=list(phase_colors.values())), legend=None),
    )
    bars = alt.Chart(melted).mark_bar(width={"band": 0.75}).encode(
        x=alt.X("session_id:O", title="Session",
                axis=alt.Axis(labelAngle=0, labelFontSize=11, titleFontSize=12)),
        y=alt.Y("count:Q", title="Turns", stack="zero",
                axis=alt.Axis(titleFontSize=12, tickMinStep=1)),
        color=alt.Color("Turn Type:N",
                        scale=alt.Scale(domain=type_display, range=type_colors),
                        title="Turn Type",
                        legend=alt.Legend(orient="bottom", direction="horizontal",
                                          symbolType="square")),
        order=alt.Order("turn_type:N"),
        tooltip=[
            alt.Tooltip("session_id:O", title="Session"),
            alt.Tooltip("Turn Type:N", title="Turn Type"),
            alt.Tooltip("count:Q", title="Count"),
            alt.Tooltip("phase:N", title="Phase"),
        ],
    )

    tl_layers = [bg2, bars]
    # Rules: use ordinal x to match bar scale — no Q/O mismatch
    if frag_sessions:
        tl_layers.append(alt.Chart(pd.DataFrame([{"session_id": s} for s in frag_sessions])
        ).mark_rule(color=C["adversarial"], strokeDash=[4, 2], strokeWidth=1.5
        ).encode(x=alt.X("session_id:O")))
    if trigger_session:
        tl_layers.append(alt.Chart(pd.DataFrame([{"session_id": trigger_session}])
        ).mark_rule(color=C["trigger"], strokeWidth=3
        ).encode(x=alt.X("session_id:O")))

    st.altair_chart(
        alt.layer(*tl_layers).properties(
            height=300,
            title=alt.TitleParams(
                text="Session Turn Composition",
                subtitle="Stacked bars: Benign · Adversarial · Trigger · Probe per session",
                fontSize=13, subtitleFontSize=10,
                color="#2C3E50", subtitleColor="#6C757D",
            )
        ),
        use_container_width=True
    )

    # Session phase chips — full phase name, not truncated
    _phase_abbr = {
        "Clean": "Clean", "Seeding": "Seeding", "Dormant": "Dormant",
        "Activation": "Active", "Post-Activation": "Post",
    }
    color_map = {
        "Clean":("benign","#1A5276"), "Seeding":("adversarial","#784212"),
        "Dormant":("dormant","#5D6D7E"), "Activation":("trigger","#7B241C"),
        "Post-Activation":("probe","#1A5276"),
    }
    chip_cols = st.columns(min(len(all_sessions), 15))
    for i, sid in enumerate(all_sessions[:len(chip_cols)]):
        ph     = _phase(sid)
        kind, fg = color_map.get(ph, ("neutral", "#2C3E50"))
        bg_c   = phase_colors.get(ph, "#ccc")
        abbr   = _phase_abbr.get(ph, ph)
        with chip_cols[i]:
            st.markdown(
                f"<div style='text-align:center;padding:5px 3px;border-radius:6px;"
                f"background:{bg_c}22;border:1px solid {bg_c};font-size:0.68rem;'>"
                f"<strong style='color:{fg}'>S{sid}</strong><br>"
                f"<span style='color:{fg};font-size:0.60rem;'>{abbr}</span></div>",
                unsafe_allow_html=True)

    st.markdown("#### Session Detail")
    interp_box(
        "Turn classification: <strong>Trigger</strong> = is_trigger=True · "
        "<strong>Probe</strong> = is_probe=True · "
        "<strong>Adversarial</strong> = fragment_id set or is_benign=False · "
        "<strong>Benign</strong> = clean interaction. "
        "Session 1 is the clean baseline — expect zero adversarial turns there."
    )
    sel_sess = st.selectbox("Expand session", all_sessions, key="sel_sess_ae")
    sess_turns = tdf[tdf["session_id"] == sel_sess][
        ["turn_id","role","turn_type","content_hash","fragment_id"]].copy()
    sess_turns.columns = ["Turn ID", "Role", "Turn Type", "Content Hash", "Fragment ID"]

    # Validate Session 1 correctness
    if sel_sess == all_sessions[0]:
        adv_in_s1 = sess_turns[sess_turns["Turn Type"] == "adversarial"]
        if adv_in_s1.empty:
            st.success("Session 1 is clean — no adversarial turns (expected for baseline).")
        else:
            st.warning(
                f"Session 1 has {len(adv_in_s1)} adversarial turn(s). "
                "Check scenario metadata — Session 1 should be the clean baseline unless "
                "the scenario explicitly marks it as an attack session."
            )

    st.dataframe(sess_turns, use_container_width=True, hide_index=True)

# ==================================================================
# TAB 3 — APS survival curve + BDI
# ==================================================================
with tab3:
    # Build per-session APS frame
    planted_by: dict[int, int] = frag_planted
    cumulative2 = 0
    aps_rows = []
    for sid, is_atk, is_trig, is_probe_s, tc, bdi, *_ in conn.execute(
        "SELECT session_id, is_attack_session, is_trigger_session, is_probe_session, "
        "turn_count, bdi_value FROM sessions WHERE run_id=? AND scenario_id=? ORDER BY session_id",
        [run_id, scenario_id]
    ).fetchall():
        cumulative2 += planted_by.get(sid, 0)
        frac = round(cumulative2 / total_frags_denom, 4) if total_frags_denom else 0.0
        if is_trig:
            ph = "trigger"
        elif cumulative2 > 0 and not is_trig and planted_by.get(sid, 0) > 0:
            ph = "adversarial"
        elif cumulative2 > 0:
            ph = "dormant"
        else:
            ph = "benign"
        aps_rows.append({"session": sid, "aps": frac, "phase": ph,
                         "is_probe": bool(is_probe_s), "bdi": bdi,
                         "fragments_planted": planted_by.get(sid, 0)})
    aps_df = pd.DataFrame(aps_rows)

    st.markdown("##### APS Survival Curve")
    interp_box(
        "Y-axis: Fragment Survival Fraction — fraction of adversarial fragments that "
        "have accumulated in memory by this session. "
        "Steps up = new fragment planted. Flat = dormant persistence. "
        "Reaches 1.0 = complete poisoning before trigger."
    )

    # Phase bands for APS
    aps_phase_ranges = []
    cur_ph  = aps_df.iloc[0]["phase"]
    ph_start = aps_df.iloc[0]["session"]
    for _, row in aps_df.iterrows():
        if row["phase"] != cur_ph or row["session"] == aps_df.iloc[-1]["session"]:
            end = row["session"] if row["phase"] != cur_ph else row["session"] + 0.5
            aps_phase_ranges.append({"phase": cur_ph, "x1": ph_start-0.5, "x2": end-0.5})
            cur_ph = row["phase"]; ph_start = row["session"]

    aps_phase_scale = alt.Scale(
        domain=["benign","adversarial","dormant","trigger","probe"],
        range=[C["benign"],C["adversarial"],C["dormant"],C["trigger"],C["probe"]],
    )
    aps_bg = alt.Chart(pd.DataFrame(aps_phase_ranges)).mark_rect(opacity=0.15).encode(
        x=alt.X("x1:Q", scale=alt.Scale(domain=[0.5, aps_df["session"].max()+0.5])),
        x2="x2:Q", y=alt.value(0), y2=alt.value(1),
        color=alt.Color("phase:N", scale=aps_phase_scale, legend=None),
    )

    # Zone labels — full readable names
    _zone_label_map = {
        "benign":     "Clean",
        "adversarial":"Seeding",
        "dormant":    "Dormant",
        "trigger":    "Activation",
        "probe":      "Probe",
    }
    seen_z, zone_lbl = set(), []
    for r in aps_phase_ranges:
        if r["phase"] not in seen_z:
            seen_z.add(r["phase"])
            mid = (r["x1"]+r["x2"])/2 + 0.5
            zone_lbl.append({"x": mid,
                             "label": _zone_label_map.get(r["phase"], r["phase"].capitalize()),
                             "phase": r["phase"]})
    zone_text = alt.Chart(pd.DataFrame(zone_lbl)).mark_text(
        align="center", dy=4, fontSize=9, fontWeight="bold", opacity=0.60
    ).encode(x="x:Q", y=alt.value(8), text="label:N",
             color=alt.Color("phase:N", scale=aps_phase_scale, legend=None),
             tooltip=alt.value(None))

    aps_line = alt.Chart(aps_df).mark_line(
        color=C["adversarial"], strokeWidth=2.5, interpolate="step-after"
    ).encode(
        x=alt.X("session:Q", title="Session",
                axis=alt.Axis(tickMinStep=1, labelFontSize=11, format="d", labelOverlap=False)),
        y=alt.Y("aps:Q", title="Fragment Survival Fraction",
                scale=alt.Scale(domain=[0,1]),
                axis=alt.Axis(format=".2f")),
        tooltip=[
            alt.Tooltip("session:Q", title="Session"),
            alt.Tooltip("aps:Q", title="Fragment Survival Fraction", format=".3f"),
            alt.Tooltip("phase:N", title="Phase"),
            alt.Tooltip("fragments_planted:Q", title="Fragments Planted"),
        ]
    )
    aps_pts = alt.Chart(aps_df[aps_df["fragments_planted"] > 0]).mark_circle(
        color=C["adversarial"], size=120, opacity=0.9
    ).encode(x="session:Q", y="aps:Q")
    probe_marks = alt.Chart(aps_df[aps_df["is_probe"]]).mark_rule(
        color=C["probe"], strokeDash=[4,2], strokeWidth=1.5
    ).encode(x="session:Q")

    aps_layers = [aps_bg, zone_text, probe_marks, aps_line, aps_pts]
    if trigger_session is not None:
        aps_layers += [
            alt.Chart(pd.DataFrame([{"x": trigger_session}])).mark_rule(
                color=C["trigger"], strokeWidth=4).encode(x="x:Q"),
            alt.Chart(pd.DataFrame([{"x": trigger_session, "y": 0.5,
                                     "t": "▼ TRIGGER ACTIVATED"}])
            ).mark_text(align="left", dx=6, fontSize=11, fontWeight="bold",
                        color=C["trigger"]).encode(x="x:Q", y="y:Q", text="t:N",
                                                   tooltip=alt.value(None)),
        ]
    st.altair_chart(alt.layer(*aps_layers).properties(height=280),
                    use_container_width=True)

    # BDI chart
    probe_aps = aps_df[aps_df["is_probe"] & aps_df["bdi"].notna()].copy()
    if not probe_aps.empty:
        st.markdown("##### Behavioral Drift Index")
        interp_box(
            "Y-axis: BDI — Behavioral Drift Index. "
            "0.0 = clean baseline behavior. "
            "A jump after the trigger session indicates successful contamination."
        )
        probe_aps["region"] = probe_aps["session"].apply(
            lambda s: "Post-trigger" if (trigger_session and s >= trigger_session)
                      else "Pre-trigger")
        bdi_sc = alt.Scale(domain=["Pre-trigger","Post-trigger"],
                           range=[C["benign"], C["trigger"]])
        bdi_l2 = alt.Chart(probe_aps).mark_line(strokeWidth=2).encode(
            x=alt.X("session:Q", title="Session",
                    axis=alt.Axis(tickMinStep=1, labelFontSize=11, format="d", labelOverlap=False)),
            y=alt.Y("bdi:Q", title="BDI (Behavioral Drift Index)",
                    scale=alt.Scale(domain=[0,1]),
                    axis=alt.Axis(format=".2f")),
            color=alt.Color("region:N", scale=bdi_sc, title="Phase",
                            legend=alt.Legend(orient="bottom", direction="horizontal")),
            tooltip=[
                alt.Tooltip("session:Q", title="Session"),
                alt.Tooltip("bdi:Q", title="BDI", format=".3f"),
                alt.Tooltip("region:N", title="Phase"),
            ]
        )
        bdi_p2 = alt.Chart(probe_aps).mark_circle(size=100).encode(
            x="session:Q", y="bdi:Q",
            color=alt.Color("region:N", scale=bdi_sc, legend=None))
        bdi_layers2 = [bdi_l2, bdi_p2]
        if trigger_session:
            bdi_layers2 += [
                alt.Chart(pd.DataFrame([{"x": trigger_session}])).mark_rule(
                    color=C["trigger"], strokeWidth=4).encode(x="x:Q"),
                alt.Chart(pd.DataFrame([{"x": trigger_session, "y": 0.50,
                                         "t": "▼ TRIGGER ACTIVATED"}])
                ).mark_text(color=C["trigger"], fontSize=11, fontWeight="bold",
                             dx=6, align="left").encode(x="x:Q", y="y:Q", text="t:N",
                                                        tooltip=alt.value(None)),
            ]
        st.altair_chart(alt.layer(*bdi_layers2).properties(height=220),
                        use_container_width=True)
