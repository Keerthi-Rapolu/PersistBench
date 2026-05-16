"""PersistBench research observability dashboard.

Read-only: loads DuckDB and passes connection via session_state.
No benchmark execution logic lives here.

Run:
    streamlit run persistbench/dashboard/app.py -- --db path/to/bench.duckdb
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_PAGES = Path(__file__).parent / "pages"

from persistbench.dashboard._theme import GLOBAL_CSS


@st.cache_resource
def _get_conn(db_path: str):
    return duckdb.connect(db_path, read_only=True)


def _resolve_db() -> str:
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            return args[i + 1]
    return str(_ROOT / "demo.duckdb")


def main():
    st.set_page_config(
        page_title="PersistBench",
        page_icon="🔬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Inject global CSS once
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    db_path = _resolve_db()
    if "conn" not in st.session_state:
        try:
            st.session_state["conn"]     = _get_conn(db_path)
            st.session_state["db_path"]  = db_path
        except Exception as exc:
            st.error(f"Cannot open database at `{db_path}`: {exc}")
            st.info("Run: `streamlit run persistbench/dashboard/app.py -- --db path/to/bench.duckdb`")
            st.stop()

    pages = {
        "Benchmark": [
            st.Page(_PAGES / "01_overview.py",          title="Overview",              icon="🏠"),
            st.Page(_PAGES / "02_attack_evolution.py",  title="Attack Evolution",      icon="🎯"),
            st.Page(_PAGES / "03_memory_provenance.py", title="Memory & Provenance",   icon="🧠"),
            st.Page(_PAGES / "04_defense_metrics.py",   title="Defense & Metrics",     icon="🛡"),
            st.Page(_PAGES / "05_cross_run.py",         title="Cross-Run Comparison",  icon="⚖️"),
            st.Page(_PAGES / "06_artifacts_about.py",   title="Artifacts & About",     icon="💾"),
        ],
    }

    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
