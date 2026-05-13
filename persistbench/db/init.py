import duckdb
from pathlib import Path

_SCHEMA = Path(__file__).parent / "schema.sql"
_DEFAULT_DB = Path("persistbench.duckdb")


def get_connection(db_path: Path = _DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with the schema applied.

    Safe to call multiple times — all tables use CREATE IF NOT EXISTS.
    Pass db_path=':memory:' for tests.
    """
    conn = duckdb.connect(str(db_path))
    conn.execute(_SCHEMA.read_text(encoding="utf-8"))
    return conn
