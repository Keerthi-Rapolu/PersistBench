"""Merge defense_demo.duckdb runs into bench.duckdb.

Run this after stopping the Streamlit dashboard (which holds bench.duckdb open):
    python scripts/merge_defense_demo.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

MAIN_DB = Path("bench.duckdb")
DEMO_DB = Path("defense_demo.duckdb")

TABLES = [
    "runs",
    "suite_metrics",
    "scenarios",
    "scenario_metrics",
    "sessions",
    "turns",
    "memory_entries",
    "memory_entry_snapshots",
    "provenance_events",
    "deletion_records",
    "forgetting_validation",
    "defense_flags",
    "governance_actions",
]

def main():
    if not DEMO_DB.exists():
        print(f"Error: {DEMO_DB} not found. Run the defense sweep first.")
        sys.exit(1)
    if not MAIN_DB.exists():
        print(f"Error: {MAIN_DB} not found.")
        sys.exit(1)

    conn = duckdb.connect(str(MAIN_DB))
    conn.execute(f"ATTACH '{DEMO_DB}' AS demo")

    demo_runs = conn.execute("SELECT run_id FROM demo.runs").fetchall()
    print(f"Merging {len(demo_runs)} run(s) from {DEMO_DB} into {MAIN_DB}:")
    for (rid,) in demo_runs:
        print(f"  {rid}")

    for table in TABLES:
        try:
            result = conn.execute(
                f"INSERT OR IGNORE INTO main.{table} SELECT * FROM demo.{table}"
            )
            n = result.rowcount if hasattr(result, 'rowcount') else '?'
            print(f"  {table}: {n} row(s) inserted")
        except Exception as e:
            print(f"  {table}: skipped ({e})")

    conn.execute("DETACH demo")
    conn.close()
    print(f"\nDone. Restart Streamlit to see all 8 defenses in cross-run charts.")

if __name__ == "__main__":
    main()
