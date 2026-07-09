from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "research_classification.duckdb"


def run() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        table = csv_path.stem
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto(?, header=true, all_varchar=true)",
            [str(csv_path)],
        )
    con.close()


if __name__ == "__main__":
    run()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"{len(tables)} tables loaded into {DB_PATH}")
    for (name,) in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {n} rows")
