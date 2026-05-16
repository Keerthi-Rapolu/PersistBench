"""PersistBench — Cross-Run Comparison"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import altair as alt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from persistbench.dashboard._theme import page_header, interp_box, C

st.markdown("<title>PersistBench — Cross-Run Comparison</title>", unsafe_allow_html=True)
page_header("Cross-Run Comparison",
            "Benchmark scorecard · Radar chart · Longitudinal metric table")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

all_runs = conn.execute(
    "SELECT r.run_id, r.model_id, r.defense_name, r.suite, r.seed, "
    "AVG(sm.aps) AS aps, AVG(sm.rls) AS rls, AVG(sm.ups) AS ups, "
    "AVG(sm.composite_score) AS composite, COUNT(sm.scenario_id) AS n_scenarios "
    "FROM runs r LEFT JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    "GROUP BY r.run_id, r.model_id, r.defense_name, r.suite, r.seed, r.created_at "
    "ORDER BY r.created_at DESC"
).fetchall()

if len(all_runs) < 2:
    st.info("Need at least 2 runs to compare. Only one run found in the database.")
    st.stop()

run_labels = {
    r[0]: (f"{r[0]}  ·  {r[2]}  ·  seed={r[4]}  ·  APS={r[5]:.3f}  ·  composite={r[8]:.3f}"
           if r[5] is not None else r[0])
    for r in all_runs
}
selected = st.multiselect(
    "Select runs to compare (choose ≥ 2)",
    list(run_labels.keys()),
    default=list(run_labels.keys())[:min(3, len(run_labels))],
    format_func=lambda k: run_labels[k],
)
if len(selected) < 2:
    st.warning("Select at least 2 runs.")
    st.stop()

baseline = st.radio("Baseline run (Δ composite reference)", selected, horizontal=True)

# ------------------------------------------------------------------
# Build comparison dataframe
# ------------------------------------------------------------------
rows = conn.execute(
    f"SELECT r.run_id, r.model_id, r.defense_name, r.suite, r.seed, "
    f"AVG(sm.aps) AS aps, AVG(sm.rls) AS rls, AVG(sm.ups) AS ups, "
    f"AVG(sm.composite_score) AS composite, COUNT(sm.scenario_id) AS n_scenarios "
    f"FROM runs r LEFT JOIN scenario_metrics sm ON r.run_id = sm.run_id "
    f"WHERE r.run_id IN ({','.join('?' for _ in selected)}) "
    f"GROUP BY r.run_id, r.model_id, r.defense_name, r.suite, r.seed",
    selected,
).fetchall()

df = pd.DataFrame(rows, columns=["Run ID", "Model", "Defense", "Suite", "Seed",
                                   "APS", "RLS", "UPS", "Composite", "Scenarios"])
baseline_val = float(df.loc[df["Run ID"] == baseline, "Composite"].values[0] or 0)
df["Δ Composite"]      = (df["Composite"] - baseline_val).round(4)
df["Pers. Resistance"] = (1 - df["APS"]).round(4)
df["Recovery Speed"]   = (1 - df["RLS"]).round(4)

# ------------------------------------------------------------------
# Duplicate/equivalent baseline guardrail
# ------------------------------------------------------------------
defense_names  = df["Defense"].unique().tolist()
composite_vals = df["Composite"].round(3).unique().tolist()
aps_vals       = df["APS"].round(3).unique().tolist()

all_same_defense  = len(defense_names) == 1
all_same_metrics  = len(composite_vals) == 1 and len(aps_vals) == 1

if all_same_defense and all_same_metrics:
    st.warning(
        f"⚠ All selected runs use the same defense ({defense_names[0]}) and have identical "
        f"metric values (Composite={composite_vals[0]:.3f}, APS={aps_vals[0]:.3f}). "
        "This does not demonstrate a meaningful defense comparison — these are equivalent "
        "baseline runs. Include runs with different defense_name values to compare quality."
    )
elif all_same_defense:
    st.info(
        f"All selected runs use the same defense ({defense_names[0]}). "
        "Consider adding runs with active defenses (TrustDecay, Quarantine, SemanticFilter) "
        "for a meaningful comparison."
    )

# ------------------------------------------------------------------
# 1. Benchmark scorecard
# ------------------------------------------------------------------
st.markdown("### Benchmark Scorecard")
interp_box(
    "Each card shows one run's defense quality. "
    "<strong>APS / RLS: lower is worse for defense quality.</strong> "
    "<strong>Composite / Pers. Resistance / Recovery Speed: higher is better.</strong> "
    "Δ Composite = difference from the selected baseline run."
)

card_cols   = st.columns(len(selected))
card_colors = ["#E8503A", "#3A8EE8", "#27AE60", "#8E44AD", "#F39C12", "#1ABC9C"]
for i, (col, (_, row)) in enumerate(zip(card_cols, df.iterrows())):
    card_c      = card_colors[i % len(card_colors)]
    delta_color = C["recovered"] if row["Δ Composite"] >= 0 else C["trigger"]
    delta_sign  = "+" if row["Δ Composite"] > 0 else ""
    composite   = row["Composite"] if row["Composite"] is not None else 0
    bar_width   = composite * 100

    with col:
        st.markdown(
            f"<div class='pb-card' style='border-top:3px solid {card_c};'>"
            f"<div style='font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;"
            f"color:#6C757D;margin-bottom:3px;'>{row['Suite']} · {row['Defense']} · seed={row['Seed']}</div>"
            f"<div style='font-size:0.95rem;font-weight:700;color:#2C3E50;'>{row['Run ID']}</div>"
            f"<div class='pb-card-value' style='color:{card_c};'>{composite:.3f}</div>"
            f"<div style='margin:6px 0;background:#E2E6EA;border-radius:3px;height:5px;'>"
            f"  <div style='background:{card_c};width:{bar_width:.1f}%;height:5px;border-radius:3px;'></div>"
            f"</div>"
            f"<div style='font-size:0.75rem;color:#6C757D;'>"
            f"APS={row['APS']:.3f} ↑worse &nbsp;·&nbsp; "
            f"RLS={row['RLS']:.3f} ↑worse &nbsp;·&nbsp; "
            f"UPS={row['UPS']:.3f} ↑better"
            f"</div>"
            f"<div style='font-size:0.72rem;color:#95A5A6;margin-top:2px;'>"
            f"{row['Scenarios']} scenario(s)</div>"
            f"<div style='margin-top:6px;font-size:0.8rem;"
            f"color:{delta_color};font-weight:500;'>"
            f"Δ {delta_sign}{row['Δ Composite']:.4f} vs baseline"
            f"</div></div>",
            unsafe_allow_html=True,
        )

# ------------------------------------------------------------------
# 2. Radar chart (matplotlib polar)
# ------------------------------------------------------------------
st.markdown("### Defense Radar Chart")
interp_box(
    "Three axes: <strong>Persistence Resistance</strong> (1−APS), "
    "<strong>Recovery Speed</strong> (1−RLS), "
    "<strong>Utility Preservation</strong> (UPS). "
    "Each axis ranges 0–1. Larger polygon = better defense. "
    "A run that only shows high Utility but low Persistence Resistance "
    "is a NoDefense baseline — it never disrupts benign turns, but also never stops attacks."
)

metrics_radar  = ["Pers. Resistance", "Recovery Speed", "UPS"]
metric_labels  = ["Persistence\nResistance\n(1−APS)", "Recovery\nSpeed\n(1−RLS)",
                  "Utility\nPreservation\n(UPS)"]
n_metrics      = len(metrics_radar)
angles         = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
angles        += angles[:1]

distinct_colors = ["#E8503A", "#3A8EE8", "#27AE60", "#8E44AD", "#F39C12", "#1ABC9C"]

fig, ax = plt.subplots(figsize=(5.5, 5.5), subplot_kw={"polar": True})
ax.set_facecolor("#FAFAFA")
fig.patch.set_facecolor("#FFFFFF")
ax.spines["polar"].set_color("#D5D8DC")
ax.set_yticks([0.25, 0.5, 0.75, 1.0])
ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], color="#AAAAAA", fontsize=7)
ax.set_ylim(0, 1)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(metric_labels, fontsize=8.5, color="#2C3E50", fontfamily="serif")
ax.tick_params(axis="x", pad=16)
ax.grid(color="#E8E8E8", linestyle="-", linewidth=0.6)

for i, (_, row) in enumerate(df.iterrows()):
    vals = [row["Pers. Resistance"], row["Recovery Speed"], row["UPS"]]
    vals_closed = vals + vals[:1]
    color = distinct_colors[i % len(distinct_colors)]
    label = f"{row['Run ID']}  ({row['Defense']}, seed={row['Seed']})"
    ax.plot(angles, vals_closed, "-o", color=color, linewidth=2.5, markersize=7,
            label=label, alpha=1.0, zorder=3)
    ax.fill(angles, vals_closed, color=color, alpha=0.10)

ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.32),
          ncol=2, fontsize=7.5, frameon=True,
          edgecolor="#E2E6EA", facecolor="white")
plt.tight_layout()

_, radar_col, _ = st.columns([1, 3, 1])
with radar_col:
    st.pyplot(fig, use_container_width=True)
plt.close(fig)

# ------------------------------------------------------------------
# 3. Metric comparison table
# ------------------------------------------------------------------
st.markdown("### Full Metric Comparison")
st.caption(
    "APS / RLS: lower is worse for defense quality. "
    "Pers. Resistance / Recovery Speed / UPS / Composite: higher is better."
)
sort_by = st.selectbox("Sort by", ["Composite", "APS", "RLS", "UPS", "Δ Composite"])
display = df[["Run ID", "Model", "Defense", "Suite", "Seed", "Scenarios",
              "APS", "RLS", "UPS", "Composite", "Δ Composite"]
             ].sort_values(sort_by, ascending=False)
st.dataframe(display, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# 4. Grouped bar chart — derived metrics (higher = always better)
# ------------------------------------------------------------------
st.markdown("### Side-by-Side Metric Bars")
interp_box(
    "All four axes are oriented so that <strong>higher = better</strong>. "
    "Persistence Resistance = 1−APS, Recovery Speed = 1−RLS, Utility = UPS."
)
melted = df.melt(id_vars=["Run ID", "Defense", "Seed"],
                 value_vars=["Pers. Resistance", "Recovery Speed", "UPS", "Composite"],
                 var_name="Metric", value_name="Score")

bar = alt.Chart(melted).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
    x=alt.X("Run ID:N", title="Run",
            axis=alt.Axis(labelAngle=-45, labelFontSize=10, titleFontSize=12,
                          labelLimit=90, labelOverlap=False)),
    y=alt.Y("Score:Q", scale=alt.Scale(domain=[0, 1]),
            axis=alt.Axis(title="Score (higher = better)", titleFontSize=11,
                          format=".2f")),
    color=alt.Color("Metric:N",
                    scale=alt.Scale(
                        domain=["Pers. Resistance","Recovery Speed","UPS","Composite"],
                        range=[C["benign"], C["recovered"], C["probe"], C["adversarial"]],
                    ),
                    title="Metric",
                    legend=alt.Legend(orient="bottom", direction="horizontal",
                                      symbolType="square")),
    column=alt.Column("Metric:N", title="",
                      header=alt.Header(labelFontSize=11, labelFontWeight="bold")),
    tooltip=[
        alt.Tooltip("Run ID:N", title="Run"),
        alt.Tooltip("Defense:N", title="Defense"),
        alt.Tooltip("Seed:Q", title="Seed"),
        alt.Tooltip("Metric:N", title="Metric"),
        alt.Tooltip("Score:Q", title="Score", format=".4f"),
    ],
).properties(width=130, height=260, padding={"bottom": 20})

st.altair_chart(bar, use_container_width=False)
