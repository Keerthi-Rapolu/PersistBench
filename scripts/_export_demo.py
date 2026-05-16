"""Export bench.duckdb -> demo.duckdb, casting TIMESTAMPTZ -> TIMESTAMP to avoid
Python 3.14 datetime serialization issues in DuckDB's Python bindings."""
import duckdb
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src_path = root / "bench.duckdb"
dst_path = root / "demo.duckdb"

dst_path.unlink(missing_ok=True)

# Phase 1: gather schema while src is open
src = duckdb.connect(str(src_path), read_only=True)
tables = [
    row[0] for row in src.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
]

# Build column projection for each table: cast TIMESTAMPTZ -> TIMESTAMP
table_exprs = {}
for t in tables:
    cols = src.execute(f"PRAGMA table_info('{t}')").fetchall()
    parts = []
    for col in cols:
        name, dtype = col[1], col[2].upper()
        if "WITH TIME ZONE" in dtype or dtype == "TIMESTAMPTZ":
            parts.append(f'"{name}"::TIMESTAMP AS "{name}"')
        else:
            parts.append(f'"{name}"')
    table_exprs[t] = ", ".join(parts)
src.close()

print(f"Copying {len(tables)} tables (TIMESTAMPTZ -> TIMESTAMP)")

# Phase 2: copy via writable dst with ATTACH
dst = duckdb.connect(str(dst_path))
dst.execute(f"ATTACH '{src_path}' AS src (READ_ONLY)")

for t in tables:
    dst.execute(f'CREATE TABLE main."{t}" AS SELECT {table_exprs[t]} FROM src."{t}"')
    n = dst.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
    print(f"  {t}: {n} rows")

dst.execute("DETACH src")
dst.close()

sz = round(dst_path.stat().st_size / 1_048_576, 2)
print(f"Done. demo.duckdb = {sz} MB")
