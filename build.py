"""Single entry point: rebuilds every table in data/ from data_untracked/ sources.

Run: .venv/bin/python build.py
"""

from __future__ import annotations

import pandas as pd

from research_classification import (
    build_asjc,
    build_correspondences_abs,
    build_correspondences_legacy,
    build_correspondences_rollup,
    build_duckdb,
    build_for_seo,
    build_leiden,
    build_openalex,
    build_registry,
    build_sdg,
    curate_for2020_division45_to_proxy,
    curate_for2020_to_openalex,
    curate_openalex_for,
    curate_openalex_subfield_to_for_group,
    curate_seo_to_sdg,
)
from research_classification.hierarchy import audit_encoding, validate_bridge, validate_canonical

DATA_DIR = build_registry.DATA_DIR
SEEDS_DIR = DATA_DIR.parent.parent / "seeds"

# Every seed file a curate_*.run() cache-guards on ("if exists, load and never regenerate").
# If the bundled .duckdb from a prior build already exists but one of these is missing, that's
# not a fresh clone -- something deleted a locked-in, possibly hand-reviewed seed, and letting
# the cache-guard silently regenerate it from scratch would quietly discard that review. See
# TODO.md and curate_for2020_to_openalex.py's module docstring for the history behind this.
_LOCKED_SEEDS = [
    "openalex_field_to_for_division.csv",
    "openalex_subfield_to_for_group.csv",
    "for2020_division_to_openalex_field.csv",
    "for2020_group_to_openalex_subfield.csv",
]


def _warn_on_missing_seeds() -> None:
    db_exists = (DATA_DIR / "research_classification.duckdb").exists()
    if not db_exists:
        return  # first build ever (fresh clone) -- nothing locked in yet, nothing to warn about
    missing = [name for name in _LOCKED_SEEDS if not (SEEDS_DIR / name).exists()]
    if missing:
        print("!" * 70)
        print("WARNING: a previous build exists, but the following locked-in seed file(s) are")
        print("missing. Any human review captured in them will be silently regenerated from")
        print("scratch (or lost) unless you restore them from git before continuing:")
        for name in missing:
            print(f"  - seeds/{name}")
        print("!" * 70)


def main() -> None:
    _warn_on_missing_seeds()
    print("1. Building canonical FOR/SEO tables...")
    for_df, seo_df = build_for_seo.run()
    validate_canonical(for_df, 23 + 213 + 1967, "FOR")
    validate_canonical(seo_df, 19 + 128 + 840, "SEO")

    print("1b. Building canonical SDG table (5 pillars + 17 goals)...")
    sdg_df = build_sdg.run()
    validate_canonical(sdg_df, 5 + 17, "SDG", require_prefix=False, level_order=["pillar", "goal"])

    print("1c. Curating (or reusing) SEO2020 division -> SDG goal (user-provided)...")
    seo_sdg_seed = curate_seo_to_sdg.run()
    curate_seo_to_sdg.write_data_table(seo_sdg_seed)

    print("2. Building canonical OpenAlex tables...")
    oax_tables = build_openalex.run()
    oax_combined = pd.concat(
        [oax_tables["openalex_domains"], oax_tables["openalex_fields"],
         oax_tables["openalex_subfields"], oax_tables["openalex_topics"]],
        ignore_index=True,
    )
    validate_canonical(
        oax_combined, 4 + 26 + 252 + 4516, "OAX",
        require_prefix=False, level_order=["domain", "field", "subfield", "topic"],
    )

    print("3. Building ASJC table and exact-ID bridge to OpenAlex...")
    build_asjc.run()

    print("4. Curating (or reusing) the hand-curated seed: OpenAlex field -> FOR division...")
    seed = curate_openalex_for.run()
    bridge_openalex_for = curate_openalex_for.to_bridge(seed)
    from research_classification.hierarchy import write_csv
    write_csv(bridge_openalex_for, DATA_DIR / "bridge_openalex_for.csv", ["source_code"])

    print("4b. Curating (or reusing) OpenAlex subfield -> FOR group (constrained + algorithmic)...")
    subfield_seed = curate_openalex_subfield_to_for_group.run()
    bridge_openalex_for_group = curate_openalex_subfield_to_for_group.to_bridge(subfield_seed)
    write_csv(bridge_openalex_for_group, DATA_DIR / "bridge_openalex_for_group.csv", ["source_code"])

    print("4c. Curating (or reusing) FOR2020 division 45 -> non-45 proxy (lexical + 2 manual overrides)...")
    division45_seed = curate_for2020_division45_to_proxy.run()
    write_csv(division45_seed, DATA_DIR / "for2020_division45_group_to_proxy.csv", ["for2020_source_code"])

    print("4d. Curating (or reusing) FOR2020 division/group -> OAX field/subfield "
          "(hand-curated, ported from an earlier project; independent of 4/4b above)...")
    curate_for2020_to_openalex.run()

    print("5. Building Leiden bridges (wikipedia_url exact join + empirical derivation), "
          "and composing FOR2020 -> Leiden through the curated FOR2020 -> OAX tables above...")
    build_leiden.run()

    print("6. Building ABS FOR2008<->2020 / SEO2008<->2020 correspondence bridges...")
    build_correspondences_abs.run()

    print("7. Building legacy FOR1998/SEO1998 bridges (via direct 1297.0 combined table)...")
    build_correspondences_legacy.run()

    print("7b. Rolling up division/group (2/4-digit) bridge rows for all four legacy vintages "
          "from the leaf-level bridges just built above, plus hand-coded overrides...")
    build_correspondences_rollup.run()

    print("8. Building the scheme_registry.csv nomenclature/level map...")
    build_registry.run()

    print("9. Validating every bridge table...")
    for_codes = set(for_df["code"])
    seo_codes = set(seo_df["code"])
    oax_codes = set(oax_combined["code"])
    canonical_lookup = {"FOR": for_codes, "SEO": seo_codes, "OAX": oax_codes}

    bridge_files = sorted(DATA_DIR.glob("bridge_*.csv"))
    for path in bridge_files:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["is_primary"] = df["is_primary"].isin(["True", "true"])
        df["confidence"] = df["confidence"].astype(float)
        validate_bridge(df, canonical_lookup, path.stem)
    print(f"   {len(bridge_files)} bridge tables OK")

    print("10. Auditing character encoding across every output table...")
    findings = []
    for path in sorted(DATA_DIR.glob("*.csv")):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        findings.extend(audit_encoding(df, path.name))
    files_with_findings = sorted({f[0] for f in findings})
    print(f"   {len(findings)} non-ASCII cell(s) found across {len(files_with_findings)} file(s): {files_with_findings}")

    print("11. Loading everything into research_classification/data/research_classification.duckdb...")
    build_duckdb.run()

    print("12. Summary:")
    total_bridge_rows = 0
    method_counts: dict[str, int] = {}
    for path in bridge_files:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        total_bridge_rows += len(df)
        for method, n in df["match_method"].value_counts().items():
            method_counts[method] = method_counts.get(method, 0) + n
    print(f"   FOR: {len(for_df)} rows, SEO: {len(seo_df)} rows, OAX: {len(oax_combined)} rows")
    print(f"   {len(bridge_files)} bridge tables, {total_bridge_rows} total rows")
    print(f"   match_method breakdown: {method_counts}")
    print("\nBuild complete.")


if __name__ == "__main__":
    main()
