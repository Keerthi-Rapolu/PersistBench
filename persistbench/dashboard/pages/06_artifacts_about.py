"""PersistBench — Artifacts & About
Merged: Research exports + benchmark description + citation.
"""
import sys, io, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import streamlit as st
from persistbench.dashboard._theme import page_header, interp_box, C

st.markdown("<title>PersistBench — Artifacts & About</title>", unsafe_allow_html=True)
page_header("Artifacts & About",
            "Download benchmark results · Benchmark description · Citation")

conn = st.session_state.get("conn")
if conn is None:
    st.error("No database connection.")
    st.stop()

# ══════════════════════════════════════════════════════════════════
# SECTION 1 — Research Artifact Exports
# ══════════════════════════════════════════════════════════════════
st.markdown("### Research Artifact Exports")

run_id = st.session_state.get("selected_run_id")
if not run_id:
    runs = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()
    if not runs:
        st.warning("No runs in database.")
    else:
        run_id = st.selectbox("Run", [r[0] for r in runs])

if run_id:
    run_meta = conn.execute(
        "SELECT benchmark_ver, model_id, defense_name, suite, seed, created_at "
        "FROM runs WHERE run_id=?", [run_id]
    ).fetchone()
    if run_meta:
        bver, model, defense, suite, seed, created = run_meta
        st.markdown(
            f"<div class='pb-card'>"
            f"<div class='pb-card-title'>Export target</div>"
            f"<div style='font-size:0.88rem;color:#2C3E50;'>"
            f"<strong>{run_id}</strong> &nbsp;·&nbsp; "
            f"model: {model} &nbsp;·&nbsp; defense: {defense} &nbsp;·&nbsp; "
            f"suite: {suite} &nbsp;·&nbsp; seed: {seed}<br>"
            f"benchmark v{bver} &nbsp;·&nbsp; created: {created}"
            f"</div></div>", unsafe_allow_html=True)

    interp_box(
        "All exports generated in-memory — no server-side files written. "
        "Filenames include the run ID for easy identification in your downloads folder. "
        "Export sanity: the run ID shown above is the same run visible in the Overview, "
        "Cross-Run, and Defense pages — metrics are consistent across all views."
    )

    # Export sanity check — confirm selected_run_id matches the current run_id
    ui_run_id = st.session_state.get("selected_run_id")
    if ui_run_id and ui_run_id != run_id:
        st.warning(
            f"⚠ Run mismatch: the Overview page has '{ui_run_id}' selected "
            f"but this export targets '{run_id}'. "
            "Navigate back to the Overview page and re-select your run, then return here."
        )
    else:
        st.success(f"✓ Export target matches selected run: `{run_id}`")

    def _csv() -> str:
        rows = conn.execute(
            "SELECT r.run_id, r.model_id, r.defense_name, r.suite, r.horizon, r.seed, "
            "sm.scenario_id, sm.aps, sm.rls, sm.ups, sm.bdi_10, sm.bdi_50, "
            "sm.composite_score, sm.attack_detected, sm.detection_session, "
            "sm.recovery_session, sm.flags_emitted, sm.false_positives "
            "FROM runs r JOIN scenario_metrics sm ON r.run_id = sm.run_id "
            "WHERE r.run_id = ?", [run_id]
        ).fetchall()
        cols = ["run_id","model_id","defense_name","suite","horizon","seed",
                "scenario_id","aps","rls","ups","bdi_10","bdi_50",
                "composite_score","attack_detected","detection_session",
                "recovery_session","flags_emitted","false_positives"]
        buf = io.StringIO()
        buf.write(",".join(cols) + "\n")
        for row in rows:
            buf.write(",".join("" if v is None else str(v) for v in row) + "\n")
        return buf.getvalue()

    def _json_summary() -> str:
        run_row = conn.execute(
            "SELECT run_id, benchmark_ver, defense_name, defense_ver, model_id, "
            "suite, horizon, seed, created_at FROM runs WHERE run_id=?", [run_id]
        ).fetchone()
        cols = ["run_id","benchmark_ver","defense_name","defense_ver",
                "model_id","suite","horizon","seed","created_at"]
        data = dict(zip(cols, run_row)) if run_row else {}
        smrows = conn.execute(
            "SELECT scenario_id, aps, rls, ups, bdi_10, bdi_50, composite_score, "
            "attack_detected, flags_emitted, false_positives "
            "FROM scenario_metrics WHERE run_id=?", [run_id]
        ).fetchall()
        scols = ["scenario_id","aps","rls","ups","bdi_10","bdi_50","composite_score",
                 "attack_detected","flags_emitted","false_positives"]
        data["scenarios"] = [dict(zip(scols, r)) for r in smrows]
        return json.dumps(data, sort_keys=True, indent=2, default=str)

    # Export cards — filenames lead with run_id for clear identification
    formats = [
        ("CSV",      "Metrics table",       "text/csv",           f"{run_id}_metrics.csv",
         "Flat CSV with all numeric metrics joined with run metadata. "
         "Ready for pandas, R, or Excel.", C["benign"]),
        ("JSON",     "Run summary",         "application/json",   f"{run_id}_summary.json",
         "Complete run summary including scenario metrics, metadata, and seed. "
         "Deterministic (sort_keys=True) for reproducible research.", C["probe"]),
        ("Markdown", "Human-readable report","text/markdown",      f"{run_id}_report.md",
         "Formatted report with 5 sections: metadata, core metrics, session breakdown, "
         "provenance summary, defense performance.", C["adversarial"]),
        ("HTML",     "Full report",         "text/html",          f"{run_id}_report.html",
         "Self-contained HTML report for sharing with collaborators "
         "or embedding in research documentation.", C["recovered"]),
    ]

    cols = st.columns(2)
    for i, (fmt, title, mime, filename, desc, color) in enumerate(formats):
        with cols[i % 2]:
            st.markdown(
                f"<div class='pb-card' style='border-top:3px solid {color};'>"
                f"<div style='font-size:0.7rem;text-transform:uppercase;letter-spacing:.07em;"
                f"color:#6C757D;'>{fmt}</div>"
                f"<div style='font-weight:600;color:#2C3E50;margin:3px 0;'>{title}</div>"
                f"<div style='font-size:0.78rem;color:#6C757D;margin-bottom:10px;'>{desc}</div>"
                f"<code style='font-size:0.72rem;color:#95A5A6;'>{filename}</code>"
                f"</div>", unsafe_allow_html=True)
            if fmt == "CSV":
                data = _csv().encode("utf-8")
            elif fmt == "JSON":
                data = _json_summary().encode("utf-8")
            else:
                try:
                    from persistbench.reporting.report_generator import generate_report
                    fmt_key = "md" if fmt == "Markdown" else "html"
                    with tempfile.TemporaryDirectory() as tmp:
                        p = generate_report(conn, run_id, tmp, fmt=fmt_key)
                        data = p.read_text(encoding="utf-8").encode("utf-8")
                except Exception as exc:
                    data = f"Error generating report: {exc}".encode("utf-8")
            st.download_button(
                label=f"Download {fmt}",
                data=data,
                file_name=filename,
                mime=mime,
                key=f"dl_{fmt}_{run_id}",
                use_container_width=True,
            )

# ══════════════════════════════════════════════════════════════════
# SECTION 2 — About
# ══════════════════════════════════════════════════════════════════
st.markdown("<div class='pb-divider'></div>", unsafe_allow_html=True)
st.markdown("### About PersistBench")

st.markdown(
    "<p style='max-width:740px;font-size:0.9rem;color:#34495E;line-height:1.7;'>"
    "PersistBench evaluates the resilience of <strong>memory-enabled LLM agents</strong> "
    "against <strong>persistent cross-session adversarial attacks</strong>. "
    "Unlike single-turn red-teaming benchmarks, PersistBench models multi-session scenarios "
    "where adversarial content is planted in early sessions, persists across session boundaries, "
    "and is activated in a later trigger session to produce unsafe or policy-violating behavior."
    "</p>", unsafe_allow_html=True)

st.markdown("<div class='pb-divider'></div>", unsafe_allow_html=True)
st.markdown("### Benchmark Suites")

suites = [
    ("SBMP", "Slow-Burn Memory Poisoning", 27, "active",
     "Adversarial content is gradually normalized across sessions across 7 domains "
     "(finance, healthcare, legal, HR, cybersecurity, education, software development). "
     "The agent accumulates a false belief until the trigger query reveals full compromise.",
     C["adversarial"]),
    ("TSCC", "Tool Supply Chain Compromise", 25, "active",
     "Adversarial fragments corrupt the agent's understanding of trusted tools or APIs. "
     "The agent is conditioned to recommend or invoke compromised resources "
     "(package poisoning, endpoint injection, CI/CD drift, credential exposure, secret management).",
     C["trigger"]),
    ("CACP", "Cross-Agent Contamination Propagation", 25, "active",
     "Adversarial memory injected via a compromised upstream agent propagates through "
     "multi-agent pipelines (finance, healthcare, legal, cybersecurity). "
     "Covers 24 unique pipeline contamination patterns across 3-agent chains.",
     C["probe"]),
]

suite_cols = st.columns(3)
for col, (abbr, name, n_scenarios, status, desc, color) in zip(suite_cols, suites):
    with col:
        st.markdown(
            f"<div class='pb-card' style='border-top:3px solid {color};'>"
            f"<div style='font-size:1.4rem;font-weight:700;color:{color};'>{abbr}</div>"
            f"<div style='font-size:0.88rem;font-weight:600;color:#2C3E50;margin:3px 0 4px;'>"
            f"{name}</div>"
            f"<div style='font-size:0.72rem;color:#1E8449;font-weight:600;'>"
            f"● IMPLEMENTED &nbsp;·&nbsp; {n_scenarios} scenarios</div>"
            f"<div style='font-size:0.82rem;color:#34495E;margin-top:8px;line-height:1.5;'>"
            f"{desc}</div></div>", unsafe_allow_html=True)

st.markdown("<div class='pb-divider'></div>", unsafe_allow_html=True)

_impl_cols = st.columns(3)
_impl_data = [
    ("V1 + V2 + V3 Implemented", C["recovered"], [
        "DuckDB analytical store + tamper-evident provenance",
        "Deterministic SLIS trace generator (v1.1 + stochastic realism)",
        "EchoBackend (oracle) + ClaudeBackend (live API, timeout=60s)",
        "Qdrant vector backend — 384-d all-MiniLM-L6-v2",
        "Embedding-based BDI<sub>sem</sub> + FVS-1–15 full suite",
        "ConsolidationEngine + ArchiveManager + SemanticPersistenceProber",
        "Provenance DAG traversal — BFS ancestor/descendant chains",
        "7-page Streamlit observability dashboard",
    ]),
    ("V4 Core — Defense Ecosystem", C["probe"], [
        "DefensePlugin base class with 6 hooks (pre_turn, pre_memory_write, ...)",
        "NoDefense · PromptLevelSanitization (PLS, 22 weighted patterns)",
        "MemoryWatermarking (MW) — eviction window + suspicion delay",
        "ToolOutputHashing (TOH) — rolling embedding centroid drift detection",
        "DualExecutionVerification (DEV) — cross-session consistency check",
        "ProvenanceScoring (PS) — multi-factor risk scoring",
        "CompositeDefense (CD = MW + PLS + TOH + PS in sequence)",
        "All defenses wired into ReplayEngine + run_benchmark.py --defense flag",
    ]),
    ("V4 Core — Evaluation Infra", C["trigger"], [
        "Extended metrics: LR, FSS, MTS, PRS, ASS, RES computed; "
        "CRA uses replay conflict heuristics (full governance-aware CRA planned)",
        "27 SBMP + 25 TSCC + 25 CACP scenarios (77 total, 7 domains)",
        "Governance pipeline: MRS, TrustGraph, RollbackEngine, ConflictGraph",
        "Leaderboard: JSON/JSONL/CSV/Markdown export + LeaderboardTable",
        "Reproducible artifact bundles (ArtifactBundler, zip/tar.gz)",
        "Ablation: MetricWeightAblation + DefenseThresholdSweep",
        "AnomalyDetector — Z-score flagging for metric outliers",
        "governance_actions table implemented; memory_conflicts planned (v5)",
    ]),
]
for col, (title, color, items) in zip(_impl_cols, _impl_data):
    with col:
        items_html = "".join(f"<li style='margin:2px 0;'>{it}</li>" for it in items)
        st.markdown(
            f"<div class='pb-card' style='border-top:3px solid {color};min-height:220px;'>"
            f"<div class='pb-card-title' style='color:{color};'>{title}</div>"
            f"<ul style='font-size:0.78rem;color:#34495E;line-height:1.6;"
            f"padding-left:16px;margin:6px 0 0;'>"
            f"{items_html}</ul></div>",
            unsafe_allow_html=True)

st.markdown("<div class='pb-divider'></div>", unsafe_allow_html=True)
st.markdown("### Citation")
st.code(
    '@misc{persistbench2026,\n'
    '  title   = {PersistBench: A Longitudinal Benchmark for Persistent\n'
    '             Adversarial Attacks on Memory-Enabled LLM Agents},\n'
    '  author  = {Rapolu, Keerthi},\n'
    '  year    = {2026},\n'
    '  note    = {V4 — Defense Ecosystem, Extended Metrics, Governance Pipeline, '
    'and 77-Scenario Evaluation Suite}\n'
    '}',
    language="bibtex")

st.caption("PersistBench V1–V4 Core Framework · DuckDB + Qdrant + Streamlit · SBMP · TSCC · CACP · 77 Scenarios · 7 Defenses · Advanced governance/streaming roadmap planned")
