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

# Allow importing from project root regardless of working directory
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_PAGES_DIR = Path(__file__).parent / "pages"

# -----------------------------------------------------------------
# DB connection (cached per session)
# -----------------------------------------------------------------

@st.cache_resource
def _get_conn(db_path: str):
    return duckdb.connect(db_path, read_only=True)


def _resolve_db() -> str:
    """Return the DB path from CLI args or fall back to the default location."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            return args[i + 1]
    default = _ROOT / "persistbench.duckdb"
    return str(default)


# -----------------------------------------------------------------
# App entry point
# -----------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="PersistBench Dashboard",
        page_icon="🔬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    db_path = _resolve_db()

    if "conn" not in st.session_state:
        try:
            st.session_state["conn"] = _get_conn(db_path)
            st.session_state["db_path"] = db_path
        except Exception as exc:
            st.error(f"Cannot open database at `{db_path}`: {exc}")
            st.info("Run: `streamlit run persistbench/dashboard/app.py -- --db path/to/bench.duckdb`")
            st.stop()

    pages = [
        st.Page(_PAGES_DIR / "01_overview.py",        title="Overview",              icon="🏠"),
        st.Page(_PAGES_DIR / "02_persistence.py",     title="Persistence Evolution", icon="📈"),
        st.Page(_PAGES_DIR / "03_provenance.py",      title="Provenance Lineage",    icon="🔗"),
        st.Page(_PAGES_DIR / "04_forgetting.py",      title="Forgetting Validation", icon="🧹"),
        st.Page(_PAGES_DIR / "05_cross_run.py",       title="Cross-Run Comparison",  icon="⚖️"),
        st.Page(_PAGES_DIR / "06_replay_timeline.py", title="Replay Timeline",       icon="🎞️"),
        st.Page(_PAGES_DIR / "07_exports.py",         title="Exports",               icon="💾"),
        st.Page(_PAGES_DIR / "08_about.py",           title="About",                 icon="ℹ️"),
    ]

    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
