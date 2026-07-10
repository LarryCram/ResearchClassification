"""Plain-assert smoke tests. Run: .venv/bin/python tests/test_resolver.py

Runs entirely against research_classification/data/ (the bundled, git-tracked CSVs and the
pre-built .duckdb file Resolver() opens by default) -- no build step required first.
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


def test_division45_cultural_proxy():
    # Most of division 45 (Indigenous Studies) DOES resolve to OAX/Leiden now, via a
    # lexically-derived (or, for two theme-buckets, user-confirmed) proxy to the
    # non-Indigenous FOR2020 group/division representing the same underlying research
    # concept -- see curate_for2020_division45_to_proxy.py. FOR1998 321207 "Indigenous
    # Health" and FOR2008 210101 "Aboriginal and Torres Strait Islander Archaeology" are
    # both confirmed (via direct query against the vintage bridges) to have their *primary*
    # FOR2020 target inside division 45 -- real historical codes that hard-failed before.
    oax = resolver.resolve("321207", "FOR1998", "OAX_FIELD")
    assert oax.match_method == "cultural_proxy"
    assert oax.label == "Medicine"  # health and wellbeing -> division 42 Health Sciences -> OAX field

    leiden = resolver.resolve("210101", "FOR2008", "LEIDEN")
    assert leiden.match_method == "cultural_proxy"
    assert leiden.label == "Social sciences and humanities"

    # the "sciences" theme's manual override (Environmental Science, not the algorithmic
    # noise-pick) is reachable directly too
    sci = resolver.resolve("450601", "FOR2020", "OAX_FIELD")  # ATSI astronomy and cosmology
    assert sci.match_method == "cultural_proxy"
    assert sci.label == "Environmental Science"
    assert sci.confidence == 0.61  # 0.7 (override) * 0.871... rounded -- proxy confidence compounds

    # bare division 45 and 4519's own catch-all both default to the "culture, language and
    # history" theme's own proxy -- the user's confirmed general landing spot for division 45
    bare45 = resolver.resolve("45", "FOR2020", "OAX_FIELD")
    bare4519 = resolver.resolve("4519", "FOR2020", "OAX_FIELD")
    nec4519 = resolver.resolve("451999", "FOR2020", "OAX_FIELD")  # 4519's own NEC field
    assert bare45.label == bare4519.label == nec4519.label == "Arts and Humanities"
    assert bare45.match_method == "cultural_proxy"

    # 4519's other two fields both -> user-confirmed proxy through FOR2020 group 4499
    # ("Other human society"), which itself already resolves cleanly (OAX "Social Sciences")
    data_tech = resolver.resolve("451906", "FOR2020", "OAX_FIELD")  # "Indigenous data and data technologies"
    methodologies = resolver.resolve("451907", "FOR2020", "OAX_FIELD")  # "Indigenous methodologies"
    assert data_tech.match_method == methodologies.match_method == "cultural_proxy"
    assert data_tech.label == methodologies.label == "Social Sciences"

    # group 4599 ("Other Indigenous studies", division 45's last remaining gap) -> same
    # user-confirmed proxy as 4519's own default, FOR2020 group 4499 "Other human society";
    # its sole field 459999 inherits the same via the group-prefix fallback tier
    other_indigenous = resolver.resolve("4599", "FOR2020", "OAX_FIELD")
    other_indigenous_field = resolver.resolve("459999", "FOR2020", "OAX_FIELD")
    assert other_indigenous.match_method == other_indigenous_field.match_method == "cultural_proxy"
    assert other_indigenous.label == other_indigenous_field.label == "Social Sciences"

    print(f"  division-45 cultural proxy OK: FOR1998 321207 -> OAX field {oax.label!r} "
          f"({oax.confidence}, {oax.match_method}); FOR2008 210101 -> Leiden {leiden.label!r} ({leiden.confidence}); "
          f"FOR2020 450601 (sciences override) -> OAX field {sci.label!r} ({sci.confidence}); "
          f"bare 45/4519/451999 -> {bare45.label!r}; 451906 -> {data_tech.label!r}; 451907 -> {methodologies.label!r}; "
          f"4599/459999 -> {other_indigenous.label!r}")


def test_group_level_precision():
    # FOR2020 groups 4904 (Pure mathematics) and 4905 (Statistics) both sit under division
    # 49, and both used to give the identical division-level OAX field/confidence -- now
    # they should differentiate (verified directly against the raw table: 4904 -> Mathematics
    # at confidence 1.0, 4905 -> Mathematics at 0.69), each more specific than division 49's
    # own confidence of 0.61 alone.
    div = resolver.resolve("49", "FOR2020", "OAX_FIELD")
    g4904 = resolver.resolve("4904", "FOR2020", "OAX_FIELD")
    g4905 = resolver.resolve("4905", "FOR2020", "OAX_FIELD")
    assert g4904.code == g4905.code == div.code == "26"  # all agree on OAX field "Mathematics"
    assert g4904.confidence != g4905.confidence  # but differentiate at group level
    assert g4904.level == "field" and g4904.match_method == "derived_empirical"

    # a FOR1998 code resolving to a 6-digit FOR2020 field should use its group ancestor
    # (4-digit) for OAX/Leiden precision, not just fall back to the coarser division
    oax_group_level = resolver.resolve("230104", "FOR1998", "OAX_FIELD")
    assert oax_group_level.confidence == g4904.confidence  # same group (4904) either way

    # OAX subfield input resolving to FOR2020 should get group-level (4-digit) output when
    # that subfield's group has coverage, not just the division-level 2-digit fallback
    from_subfield = resolver.resolve("1908", "OAX", "FOR2020")  # Geophysics subfield
    assert len(from_subfield.code) == 4 and from_subfield.level == "group"

    print(f"  group-level precision OK: division 49={div.confidence}, group 4904={g4904.confidence}, "
          f"group 4905={g4905.confidence}; OAX subfield->FOR2020 gives group-level {from_subfield.code!r}")


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
    # Resolver(db_path=...) pointed explicitly at the same bundled .duckdb file the default
    # constructor opens automatically should agree -- same data, two ways to load it.
    db_path = DATA_DIR / "research_classification.duckdb"
    assert db_path.exists(), "research_classification.duckdb should always be present (git-tracked, bundled package data)"
    explicit = Resolver(db_path=db_path)
    a = resolver.resolve("30", "FOR2020", "FOR2020")
    b = explicit.resolve("30", "FOR2020", "FOR2020")
    assert a.code == b.code and a.label == b.label
    print("  Resolver(db_path=...) against the bundled .duckdb file agrees with the default constructor")


def test_csv_fallback_matches_default():
    # Resolver._load_bundled_csvs() (the fallback path used if the bundled .duckdb file
    # can't be opened, e.g. a duckdb version mismatch) should give identical results to the
    # default fast path -- same source CSVs either way, just loaded differently.
    from_csv = Resolver.__new__(Resolver)
    from_csv._resource_ctx = None
    from_csv._con = Resolver._load_bundled_csvs()
    a = resolver.resolve("230104", "FOR1998", "OAX_FIELD")
    b = from_csv.resolve("230104", "FOR1998", "OAX_FIELD")
    assert a.code == b.code and a.label == b.label and a.confidence == b.confidence
    print("  CSV-fallback path agrees with the default bundled-.duckdb path")


def test_exhaustive_for2020_to_oax_leiden_coverage():
    # Every single FOR2020 code (2203 total: 23 divisions, 213 groups, 1967 fields) resolves
    # to both OAX_FIELD and LEIDEN -- division 45's cultural-proxy chain (see
    # curate_for2020_division45_to_proxy.py) now covers all of it, including the last
    # remaining gap (group 4599, proxied to FOR2020 group 4499 "Other human society"). This
    # is a permanent regression guard: any future failure here means something broke.
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for to_scheme in ("OAX_FIELD", "LEIDEN"):
        failures = set()
        for code in for_df["code"]:
            try:
                resolver.resolve(code, "FOR2020", to_scheme)
            except LookupError:
                failures.add(code)
        assert not failures, f"{to_scheme}: unexpected LookupError(s) for {failures}"
    print(f"  exhaustive FOR2020 coverage OK: all {len(for_df)}/{len(for_df)} codes resolve to both OAX_FIELD and LEIDEN")


def test_exhaustive_legacy_for_coverage():
    # Every FOR1998 and FOR2008 code that appears as a source_code in its vintage bridge
    # (898 and 1238 respectively) should also resolve to both OAX_FIELD and LEIDEN, since
    # they all resolve to *some* FOR2020 code first and FOR2020 is now fully covered (see
    # test_exhaustive_for2020_to_oax_leiden_coverage). A permanent regression guard.
    for from_scheme, bridge_file in [("FOR1998", "bridge_for1998_for2020.csv"), ("FOR2008", "bridge_for2008_for2020.csv")]:
        bridge = pd.read_csv(DATA_DIR / bridge_file, dtype=str, keep_default_na=False)
        codes = bridge["source_code"].unique()
        for to_scheme in ("OAX_FIELD", "LEIDEN"):
            failures = set()
            for code in codes:
                try:
                    resolver.resolve(code, from_scheme, to_scheme)
                except LookupError:
                    failures.add(code)
            assert not failures, f"{from_scheme} -> {to_scheme}: unexpected LookupError(s) for {failures}"
        print(f"  exhaustive {from_scheme} coverage OK: all {len(codes)}/{len(codes)} codes resolve to both OAX_FIELD and LEIDEN")


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
        test_division45_cultural_proxy,
        test_exhaustive_for2020_to_oax_leiden_coverage,
        test_exhaustive_legacy_for_coverage,
        test_group_level_precision,
        test_leading_zero_normalization,
        test_explicit_db_path_matches_bundled,
        test_csv_fallback_matches_default,
        test_lookup_error,
    ]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")
