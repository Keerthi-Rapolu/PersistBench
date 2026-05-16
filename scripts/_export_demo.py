"""Export bench.duckdb -> demo.duckdb via ATTACH copy (no raw file copy, no WAL residue)."""
import duckdb
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src_path = root / "bench.duckdb"
dst_path = root / "demo.duckdb"

dst_path.unlink(missing_ok=True)

# Get table list from source
src = duckdb.connect(str(src_path), read_only=True)
tables = [
    row[0] for row in src.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
]
src.close()
print(f"Copying {len(tables)} tables: {tables}")

# Copy via writable destination connection
dst = duckdb.connect(str(dst_path))
dst.execute(f"ATTACH '{src_path}' AS src (READ_ONLY)")
for t in tables:
    dst.execute(f"CREATE TABLE main.{t} AS SELECT * FROM src.{t}")
    n = dst.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0]
    print(f"  {t}: {n} rows")

dst.execute("DETACH src")
dst.close()

sz = round(dst_path.stat().st_size / 1_048_576, 2)
print(f"Done. demo.duckdb = {sz} MB")
