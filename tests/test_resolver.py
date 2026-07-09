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
    for from_scheme, to_scheme, fname in [("FOR2020", "FOR2020", "for_2020.csv"), ("SEO2020", "SEO2020", "seo_2020.csv")]:
        df = pd.read_csv(DATA_DIR / fname, dtype=str, keep_default_na=False)
        for code in df["code"]:
            result = resolver.resolve(code, from_scheme, to_scheme)
            assert result.match_method == "identity", f"{from_scheme} {code}: {result.match_method}"
            assert result.confidence == 1.0
    print(f"  identity round-trip OK ({len(df)} {to_scheme} codes, plus earlier scheme)")


def test_bridge_primary_uniqueness():
    for path in sorted(DATA_DIR.glob("bridge_*.csv")):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["is_primary"] = df["is_primary"].isin(["True", "true"])
        counts = df.groupby(["source_system", "source_code", "system"])["is_primary"].sum()
        bad = counts[counts != 1]
        assert bad.empty, f"{path.name}: {len(bad)} source-code group(s) without exactly one primary"
    print("  bridge is_primary uniqueness OK")


def test_collision_resolved_by_explicit_from_scheme():
    # code 300101 means "Soil Physics" under FOR1998 but "Agricultural biotechnology
    # diagnostics" under FOR2020 -- a real collision (48% of FOR1998's 898 codes collide
    # with a differently-meaning FOR2020 code this way). Both are reachable unambiguously
    # simply because from_scheme is always explicit -- no guessing, no hard-fail needed.
    as_for1998 = resolver.resolve("300101", "FOR1998", "FOR2020")
    as_for2020 = resolver.resolve("300101", "FOR2020", "FOR2020")
    assert as_for1998.code == "410605" and as_for1998.label == "Soil physics"
    assert as_for2020.code == "300101" and "Agricultural" in as_for2020.label
    print(f"  collision resolved OK: FOR1998/300101={as_for1998.label!r}, FOR2020/300101={as_for2020.label!r}")


def test_asjc_exact_join():
    # ASJC code 16 = Chemistry (verified 100% exact match with OpenAlex field_id) -- ASJC
    # codes ARE OpenAlex field/subfield codes, so this resolves directly as OAX input.
    result = resolver.resolve("16", "OAX", "OAX_FIELD")
    assert result.match_method == "identity"
    assert result.label == "Chemistry"
    print(f"  ASJC/OpenAlex exact-ID join OK: {result.label!r}")


def test_leiden_for_derivation():
    # Leiden main_field codes aren't a valid from_scheme (Leiden is output-only, never an
    # administrative code anyone assigns) -- this exercises the reverse instead: a FOR
    # division resolving to its correctly-directed Leiden parent.
    for code in ["44", "38", "43"]:  # Human Society, Economics, History
        result = resolver.resolve(code, "FOR2020", "LEIDEN")
        assert result.match_method == "derived_empirical"
        print(f"  FOR2020 {code} -> Leiden '{result.label}' (confidence={result.confidence})")


def test_for2008_known_code():
    # spot-checked directly against the raw ABS correspondence table earlier
    result = resolver.resolve("010101", "FOR2008", "FOR2020")
    assert result.code == "490401"
    assert result.match_method == "explicit_official"
    print(f"  FOR2008 010101 -> FOR2020 {result.code} ({result.label!r}) OK")


def test_resolve_forward_pre2000():
    # FOR1998 230104 "Category Theory, K Theory, Homological Algebra" -> FOR2020 490403,
    # then up to OAX field/subfield and Leiden main field (never a fabricated OAX topic guess)
    for2020 = resolver.resolve("230104", "FOR1998", "FOR2020")
    oax_field = resolver.resolve("230104", "FOR1998", "OAX_FIELD")
    leiden = resolver.resolve("230104", "FOR1998", "LEIDEN")
    assert for2020.code == "490403"
    assert oax_field.level == "field"  # up the hierarchy only -- never "topic"
    assert oax_field.match_method == "derived_empirical"
    assert leiden.level == "main_field"
    assert leiden.label == "Mathematics and computer science"
    print(f"  FOR1998 230104 -> FOR2020 {for2020.code}, "
          f"OAX field {oax_field.label!r} ({oax_field.confidence}), "
          f"Leiden {leiden.label!r} ({leiden.confidence}) OK")


def test_oax_topic_hard_fails_from_for_family():
    try:
        resolver.resolve("230104", "FOR1998", "OAX_TOPIC")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "OAX_TOPIC" in str(e)
    print("  OAX_TOPIC correctly hard-fails from a FOR-family input")


def test_oax_down_direction_hard_fails():
    try:
        resolver.resolve("16", "OAX", "OAX_TOPIC")  # field -> topic is "down"
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "down" in str(e)
    # but topic -> field ("up") works fine
    result = resolver.resolve("10001", "OAX", "OAX_FIELD")
    assert result.level == "field" and result.match_method == "identity"
    print("  OAX down-direction correctly rejected; up-direction (topic->field) works")


def test_oax_domain_too_coarse_for_for2020():
    try:
        resolver.resolve("1", "OAX", "FOR2020")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "domain" in str(e)
    print("  OAX domain-level input correctly rejected for FOR2020 (needs field-level precision)")


def test_seo_cannot_target_oax_or_leiden():
    for to_scheme in ("OAX_FIELD", "OAX_DOMAIN", "OAX_SUBFIELD", "OAX_TOPIC", "LEIDEN"):
        try:
            resolver.resolve("10", "SEO2020", to_scheme)
            raise AssertionError(f"expected ValueError for SEO2020 -> {to_scheme}")
        except ValueError as e:
            assert "SEO" in str(e)
    print("  SEO2020 correctly cannot target any OAX/Leiden scheme")


def test_indigenous_studies_gap():
    # FOR division 45 (Indigenous Studies) genuinely has no OpenAlex/Leiden equivalent --
    # must report this as an informative LookupError, not silently fabricate a mapping.
    row = resolver._con.execute(
        "SELECT source_code FROM bridge_for1998_for2020 WHERE canonical_code LIKE '45%' "
        "AND is_primary = 'True' LIMIT 1"
    ).fetchone()
    assert row is not None
    try:
        resolver.resolve(row[0], "FOR1998", "OAX_FIELD")
        raise AssertionError("expected LookupError")
    except LookupError as e:
        assert "genuinely absent" in str(e)
    print(f"  FOR1998 {row[0]} (division 45) correctly reports OAX as genuinely absent")


def test_leading_zero_normalization():
    # FOR2008 codes in divisions 01-09 (556 of them) lose their leading zero if read as an
    # int by pandas/JSON/Excel -- e.g. "010101" becomes 10101. Since FOR2008 codes are
    # always exactly 6 digits, an observed length of 5 is unambiguous: recover it.
    from_int = resolver.resolve(10101, "FOR2008", "FOR2020")
    from_str_padded = resolver.resolve("010101", "FOR2008", "FOR2020")
    assert from_int.code == from_str_padded.code == "490401"
    assert from_int.input_value == "010101"  # normalized before use
    print("  leading-zero recovery OK: int 10101 -> '010101' -> same result as padded string")


def test_explicit_db_path_matches_bundled():
    # Resolver(db_path=...) against the exported .duckdb file should agree with the
    # default in-memory-from-bundled-CSVs path -- same data, two ways to load it.
    db_path = ROOT / "data" / "research_classification.duckdb"
    if not db_path.exists():
        print("  (skipped: run `python build.py` first to produce data/research_classification.duckdb)")
        return
    exported = Resolver(db_path=db_path)
    a = resolver.resolve("30", "FOR2020", "FOR2020")
    b = exported.resolve("30", "FOR2020", "FOR2020")
    assert a.code == b.code and a.label == b.label
    print("  Resolver(db_path=...) against the exported file agrees with the bundled default")


def test_lookup_error():
    try:
        resolver.resolve("not-a-real-code", "FOR2020", "FOR2020")
        raise AssertionError("expected LookupError")
    except LookupError:
        pass
    print("  LookupError on unknown input OK")


if __name__ == "__main__":
    tests = [
        test_row_counts,
        test_identity_round_trip,
        test_bridge_primary_uniqueness,
        test_collision_resolved_by_explicit_from_scheme,
        test_asjc_exact_join,
        test_leiden_for_derivation,
        test_for2008_known_code,
        test_resolve_forward_pre2000,
        test_oax_topic_hard_fails_from_for_family,
        test_oax_down_direction_hard_fails,
        test_oax_domain_too_coarse_for_for2020,
        test_seo_cannot_target_oax_or_leiden,
        test_indigenous_studies_gap,
        test_leading_zero_normalization,
        test_explicit_db_path_matches_bundled,
        test_lookup_error,
    ]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")
