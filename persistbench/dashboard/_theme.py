"""Shared visual theme for the PersistBench dashboard.

Pastel, academic, systems-research aesthetic.
White background, soft shadows, research-grade typography.
"""

# ------------------------------------------------------------------
# Attack-state color semantics (pastel)
# ------------------------------------------------------------------
C = {
    "benign":      "#8BB8E8",   # soft blue        — clean / safe
    "dormant":     "#C4C8D4",   # soft gray         — dormant / unknown
    "adversarial": "#F4A870",   # soft orange       — contaminated
    "trigger":     "#E88A8A",   # soft red          — activated / triggered
    "recovered":   "#8EC99E",   # soft green        — recovered / clean
    "quarantine":  "#F4E08A",   # soft yellow       — quarantined
    "deleted":     "#AEAEAE",   # muted charcoal    — deleted / forgotten
    "probe":       "#C4A8E8",   # soft purple       — probe / observation
    "neutral":     "#F0F2F5",   # off-white         — background
}

# Lighter fills for background rectangles (20% opacity via hex suffix)
FILL = {k: v + "33" for k, v in C.items()}

# Altair-compatible lists
STATE_DOMAIN = ["benign", "dormant", "adversarial", "trigger", "recovered",
                "quarantine", "deleted", "probe"]
STATE_RANGE  = [C[s] for s in STATE_DOMAIN]

# ------------------------------------------------------------------
# Typography / layout
# ------------------------------------------------------------------
FONT        = "Georgia, 'Times New Roman', serif"
MONO        = "'JetBrains Mono', 'Courier New', monospace"
TEXT        = "#2C3E50"
MUTED       = "#6C757D"
CARD_BG     = "#F8F9FA"
BORDER      = "#E2E6EA"
PAGE_BG     = "#FFFFFF"

# ------------------------------------------------------------------
# Global CSS (inject once in app.py)
# ------------------------------------------------------------------
GLOBAL_CSS = """
<style>
/* ---- Typography ---- */
html, body, [class*="css"] {
    font-family: Georgia, 'Times New Roman', serif;
    color: #2C3E50;
}
h1 { font-size: 1.7rem; font-weight: 600; color: #1A252F; margin-bottom: .15rem; }
h2 { font-size: 1.2rem; font-weight: 500; color: #2C3E50; margin-top: 1.4rem; }
h3 { font-size: 1.0rem; font-weight: 500; color: #34495E; }

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: #F8F9FA;
    border-right: 1px solid #E2E6EA;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2 {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6C757D;
    margin-top: 1rem;
}

/* ---- Metric cards ---- */
[data-testid="stMetric"] {
    background: #F8F9FA;
    border: 1px solid #E2E6EA;
    border-radius: 8px;
    padding: 12px 16px;
}
[data-testid="stMetricLabel"] { color: #6C757D; font-size: 0.78rem; }
[data-testid="stMetricValue"] { color: #2C3E50; font-size: 1.5rem; font-weight: 600; }

/* ---- Cards ---- */
.pb-card {
    background: #F8F9FA;
    border: 1px solid #E2E6EA;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.pb-card-title {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #6C757D;
    margin-bottom: 4px;
}
.pb-card-value {
    font-size: 1.6rem;
    font-weight: 600;
    color: #2C3E50;
    font-family: 'Georgia', serif;
}

/* ---- State badges ---- */
.badge {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 12px;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.04em;
}
.badge-benign      { background: #D4E8F8; color: #1A5276; }
.badge-adversarial { background: #FDEBD0; color: #784212; }
.badge-trigger     { background: #FADBD8; color: #7B241C; }
.badge-recovered   { background: #D5F5E3; color: #1E8449; }
.badge-dormant     { background: #EAECEE; color: #5D6D7E; }
.badge-probe       { background: #E8DAEF; color: #6C3483; }
.badge-v2          { background: #EBF5FB; color: #1A5276; border: 1px dashed #85C1E9; }

/* ---- Section divider ---- */
.pb-divider { border-top: 1px solid #E2E6EA; margin: 24px 0; }

/* ---- Interpretation box ---- */
.pb-interp {
    background: #EBF5FB;
    border-left: 3px solid #8BB8E8;
    padding: 10px 16px;
    border-radius: 0 6px 6px 0;
    font-size: 0.88rem;
    color: #1A5276;
    margin: 8px 0 16px 0;
}

/* ---- Warning / v2 notice ---- */
.pb-v2-notice {
    background: #FEF9E7;
    border: 1px dashed #F4D03F;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 0.85rem;
    color: #7D6608;
    margin: 12px 0;
}

/* ---- Dataframe ---- */
[data-testid="stDataFrame"] { border: 1px solid #E2E6EA; border-radius: 6px; }

/* ---- Tabs ---- */
[data-testid="stTabs"] button { font-family: Georgia, serif; font-size: 0.85rem; }
</style>
"""

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def page_header(title: str, subtitle: str = "") -> None:
    """Render the standard page header with optional subtitle."""
    import streamlit as st
    st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(
            f"<p style='color:#6C757D;font-size:0.88rem;margin-top:-4px;'>{subtitle}</p>",
            unsafe_allow_html=True,
        )
    st.markdown("<div class='pb-divider'></div>", unsafe_allow_html=True)


def interp_box(text: str) -> None:
    import streamlit as st
    st.markdown(f"<div class='pb-interp'>{text}</div>", unsafe_allow_html=True)


def v2_notice(text: str) -> None:
    import streamlit as st
    st.markdown(
        f"<div class='pb-v2-notice'>🔬 {text}</div>",
        unsafe_allow_html=True,
    )


def badge(label: str, kind: str = "benign") -> str:
    return f"<span class='badge badge-{kind}'>{label}</span>"
