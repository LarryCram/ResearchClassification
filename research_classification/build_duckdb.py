from __future__ import annotations

import duckdb

from .paths import DB_PATH, DUCKDB_SOURCE_DIRS, OUTPUT_DIR
# Resolver._load_bundled_db()'s docstring explains why the pre-built .duckdb is the default
# at runtime (~10ms to open vs ~360ms to rebuild in-memory from the CSVs) -- the CSVs stay
# bundled too, both for git-diffable transparency and as Resolver()'s automatic fallback if
# this exact file can't be opened by whatever duckdb version ends up installed (its on-disk
# storage format isn't guaranteed compatible indefinitely across duckdb versions).


def run() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for source_dir in DUCKDB_SOURCE_DIRS:
        for csv_path in sorted(source_dir.glob("*.csv")):
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
