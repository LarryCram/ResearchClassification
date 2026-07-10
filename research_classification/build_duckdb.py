from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = ROOT / "research_classification" / "data"  # bundled package data, git-tracked
DB_PATH = CSV_DIR / "research_classification.duckdb"  # also bundled + git-tracked, see
# Resolver._load_bundled_db()'s docstring for why this is the default at runtime (~10ms to
# open vs ~360ms to rebuild in-memory from the CSVs) -- the CSVs stay bundled too, both for
# git-diffable transparency and as Resolver()'s automatic fallback if this exact file can't
# be opened by whatever duckdb version ends up installed (its on-disk storage format isn't
# guaranteed compatible indefinitely across duckdb versions).


def run() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    for csv_path in sorted(CSV_DIR.glob("*.csv")):
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
