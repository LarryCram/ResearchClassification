"""Plain-assert smoke tests. Run: .venv/bin/python tests/test_resolver.py

Runs entirely against the CSVs bundled inside research_classification/data/ -- no build
step required first (that's the whole point of Resolver() defaulting to an in-memory build
from package data). test_explicit_db_path_matches_bundled additionally sanity-checks
Resolver(db_path=...) against the exported .duckdb file if `python build.py` has been run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from research_classification import Resolver

DATA_DIR = ROOT / "research_classification" / "data"
resolver = Resolver()


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
    for table, expected in counts.items():
        n = resolver._con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == expected, f"{table}: expected {expected} rows, got {n}"
    print(f"  row counts OK ({len(counts)} tables)")


def test_identity_round_trip():
    for system, fname in [("FOR", "for_2020.csv"), ("SEO", "seo_2020.csv")]:
        df = pd.read_csv(DATA_DIR / fname, dtype=str, keep_default_na=False)
        for code in df["code"]:
            result = resolver.resolve(code, system)
            assert result.match_method == "identity", f"{system} {code}: {result.match_method}"
            assert result.confidence == 1.0
    print(f"  identity round-trip OK ({len(df)} {system} codes, plus earlier systems)")


def test_bridge_primary_uniqueness():
    for path in sorted(DATA_DIR.glob("bridge_*.csv")):
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
    for_result = resolver.resolve("30", "FOR")
    seo_result = resolver.resolve("10", "SEO")
    oax_result = resolver.resolve("1", "OAX")
    assert for_result.system == "FOR" and seo_result.system == "SEO" and oax_result.system == "OAX"
    assert for_result.canonical_label != seo_result.canonical_label != oax_result.canonical_label
    try:
        resolver.resolve("30", "SEO")  # "30" is a valid FOR division but not a valid SEO code
        raise AssertionError("expected LookupError: '30' is not a valid SEO code")
    except LookupError:
        pass
    print(f"  system isolation OK: FOR/30={for_result.canonical_label!r}, "
          f"SEO/10={seo_result.canonical_label!r}, OAX/1={oax_result.canonical_label!r}; "
          f"cross-system lookup ('30' as SEO) correctly raises LookupError")


def test_asjc_exact_join():
    # ASJC code 16 = Chemistry (verified 100% exact match with OpenAlex field_id)
    result = resolver.resolve("16", "OAX")
    assert result.match_method == "identity"
    assert result.canonical_label == "Chemistry"
    print(f"  ASJC/OpenAlex exact-ID join OK: {result.canonical_label!r}")


def test_leiden_for_derivation():
    main_field = pd.read_csv(DATA_DIR / "leiden_main_field.csv", dtype=str, keep_default_na=False)
    for _, row in main_field.iterrows():
        result = resolver.resolve(row["code"], "FOR")
        assert result.match_method == "derived_empirical"
        print(f"  Leiden '{row['label']}' -> FOR '{result.canonical_label}' (confidence={result.confidence})")


def test_for2008_known_code():
    # spot-checked directly against the raw ABS correspondence table earlier
    result = resolver.resolve("010101", "FOR")
    assert result.canonical_code == "490401"
    assert result.match_method == "explicit_official"
    print(f"  FOR2008 010101 -> FOR2020 {result.canonical_code} ({result.canonical_label!r}) OK")


def test_resolve_forward_pre2000():
    # RFCD1998 230104 "Category Theory, K Theory, Homological Algebra" -> FOR2020 490403,
    # then up to OAX field and Leiden main field (never a fabricated OAX topic guess)
    results = resolver.resolve_forward("230104", "FOR")
    assert results["FOR2020"].code == "490403"
    assert results["OAX"].level == "field"  # up the hierarchy only -- never "topic"
    assert results["OAX"].method == "derived_empirical"
    assert results["Leiden"].level == "main_field"
    assert results["Leiden"].label == "Mathematics and computer science"
    print(f"  RFCD1998 230104 -> FOR2020 {results['FOR2020'].code}, "
          f"OAX field {results['OAX'].label!r} ({results['OAX'].confidence}), "
          f"Leiden {results['Leiden'].label!r} ({results['Leiden'].confidence}) OK")


def test_resolve_forward_indigenous_studies_gap():
    # FOR division 45 (Indigenous Studies) genuinely has no OpenAlex/Leiden equivalent --
    # must report "unavailable" with a reason, not silently fabricate or raise.
    row = resolver._con.execute(
        "SELECT source_code FROM bridge_asrc1998_for2020 WHERE canonical_code LIKE '45%' "
        "AND is_primary = 'True' LIMIT 1"
    ).fetchone()
    assert row is not None
    results = resolver.resolve_forward(row[0], "FOR")
    assert results["OAX"].method == "unavailable" and results["OAX"].code == ""
    assert results["Leiden"].method == "unavailable" and results["Leiden"].code == ""
    assert "genuinely absent" in results["OAX"].note
    print(f"  RFCD1998 {row[0]} (division 45) correctly reports OAX/Leiden as unavailable")


def test_resolve_forward_seo_has_no_oax_leiden():
    row = resolver._con.execute("SELECT source_code FROM bridge_asrc1998_seo2020 LIMIT 1").fetchone()
    assert row is not None
    results = resolver.resolve_forward(row[0], "SEO")
    assert results["SEO2020"].code
    assert results["OAX"].method == "unavailable"
    assert results["Leiden"].method == "unavailable"
    print(f"  SEO1998 {row[0]} -> SEO2020 {results['SEO2020'].code}, OAX/Leiden correctly unavailable by design")


def test_lookup_error():
    try:
        resolver.resolve("not-a-real-code", "FOR")
        raise AssertionError("expected LookupError")
    except LookupError:
        pass
    print("  LookupError on unknown input OK")


def test_explicit_db_path_matches_bundled():
    # Resolver(db_path=...) against the exported .duckdb file should agree with the
    # default in-memory-from-bundled-CSVs path -- same data, two ways to load it.
    db_path = ROOT / "data" / "research_classification.duckdb"
    if not db_path.exists():
        print("  (skipped: run `python build.py` first to produce data/research_classification.duckdb)")
        return
    exported = Resolver(db_path=db_path)
    a = resolver.resolve("30", "FOR")
    b = exported.resolve("30", "FOR")
    assert a.canonical_code == b.canonical_code and a.canonical_label == b.canonical_label
    print("  Resolver(db_path=...) against the exported file agrees with the bundled default")


if __name__ == "__main__":
    tests = [
        test_row_counts,
        test_identity_round_trip,
        test_bridge_primary_uniqueness,
        test_system_isolation,
        test_asjc_exact_join,
        test_leiden_for_derivation,
        test_for2008_known_code,
        test_resolve_forward_pre2000,
        test_resolve_forward_indigenous_studies_gap,
        test_resolve_forward_seo_has_no_oax_leiden,
        test_explicit_db_path_matches_bundled,
        test_lookup_error,
    ]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")
