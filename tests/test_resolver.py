"""Plain-assert smoke tests. Run: .venv/bin/python tests/test_resolver.py
(requires `python build.py` to have been run first so data/research_classification.duckdb exists)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from research_classification import resolve
from research_classification.resolver import _connection


def test_row_counts():
    counts = {
        "for_2020": 2203,
        "seo_2020": 987,
        "leiden_main_field": 5,
        "openalex_domains": 4,
        "openalex_fields": 26,
        "openalex_subfields": 252,
        "openalex_topics": 4516,
    }
    con = _connection()
    for table, expected in counts.items():
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == expected, f"{table}: expected {expected} rows, got {n}"
    print(f"  row counts OK ({len(counts)} tables)")


def test_identity_round_trip():
    for system, fname in [("FOR", "for_2020.csv"), ("SEO", "seo_2020.csv")]:
        df = pd.read_csv(ROOT / "data" / fname, dtype=str, keep_default_na=False)
        for code in df["code"]:
            result = resolve(code, system)
            assert result.match_method == "identity", f"{system} {code}: {result.match_method}"
            assert result.confidence == 1.0
    print(f"  identity round-trip OK ({len(df)} {system} codes, plus earlier systems)")


def test_bridge_primary_uniqueness():
    for path in sorted((ROOT / "data").glob("bridge_*.csv")):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["is_primary"] = df["is_primary"].isin(["True", "true"])
        counts = df.groupby(["source_system", "source_code", "system"])["is_primary"].sum()
        bad = counts[counts != 1]
        assert bad.empty, f"{path.name}: {len(bad)} source-code group(s) without exactly one primary"
    print("  bridge is_primary uniqueness OK")


def test_system_isolation():
    # FOR divisions are numbered 30-52,99 and SEO divisions 10-28 -- ANZSRC 2020 happens not
    # to collide at the division level, but the same numeric code is still routed to a
    # completely different table depending on `system`, which is what actually matters:
    # passing the wrong system for a code that IS valid in the other system must fail loudly
    # rather than silently returning a wrong answer.
    for_result = resolve("30", "FOR")
    seo_result = resolve("10", "SEO")
    oax_result = resolve("1", "OAX")
    assert for_result.system == "FOR" and seo_result.system == "SEO" and oax_result.system == "OAX"
    assert for_result.canonical_label != seo_result.canonical_label != oax_result.canonical_label
    try:
        resolve("30", "SEO")  # "30" is a valid FOR division but not a valid SEO code
        raise AssertionError("expected LookupError: '30' is not a valid SEO code")
    except LookupError:
        pass
    print(f"  system isolation OK: FOR/30={for_result.canonical_label!r}, "
          f"SEO/10={seo_result.canonical_label!r}, OAX/1={oax_result.canonical_label!r}; "
          f"cross-system lookup ('30' as SEO) correctly raises LookupError")


def test_asjc_exact_join():
    # ASJC code 16 = Chemistry (verified 100% exact match with OpenAlex field_id)
    result = resolve("16", "OAX")
    assert result.match_method == "identity"
    assert result.canonical_label == "Chemistry"
    print(f"  ASJC/OpenAlex exact-ID join OK: {result.canonical_label!r}")


def test_leiden_for_derivation():
    main_field = pd.read_csv(ROOT / "data" / "leiden_main_field.csv", dtype=str, keep_default_na=False)
    for _, row in main_field.iterrows():
        result = resolve(row["code"], "FOR")
        assert result.match_method == "derived_empirical"
        print(f"  Leiden '{row['label']}' -> FOR '{result.canonical_label}' (confidence={result.confidence})")


def test_for2008_known_code():
    # spot-checked directly against the raw ABS correspondence table earlier
    result = resolve("010101", "FOR")
    assert result.canonical_code == "490401"
    assert result.match_method == "explicit_official"
    print(f"  FOR2008 010101 -> FOR2020 {result.canonical_code} ({result.canonical_label!r}) OK")


def test_lookup_error():
    try:
        resolve("not-a-real-code", "FOR")
        raise AssertionError("expected LookupError")
    except LookupError:
        pass
    print("  LookupError on unknown input OK")


if __name__ == "__main__":
    tests = [
        test_row_counts,
        test_identity_round_trip,
        test_bridge_primary_uniqueness,
        test_system_isolation,
        test_asjc_exact_join,
        test_leiden_for_derivation,
        test_for2008_known_code,
        test_lookup_error,
    ]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")
