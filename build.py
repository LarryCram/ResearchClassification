"""Single entry point: rebuilds every table in data/ from data_untracked/ sources.

Run: .venv/bin/python build.py
"""

from __future__ import annotations

import pandas as pd

from research_classification import (
    build_asjc,
    build_correspondences_abs,
    build_correspondences_legacy,
    build_duckdb,
    build_for_seo,
    build_leiden,
    build_openalex,
    build_registry,
    curate_openalex_for,
    curate_openalex_subfield_to_for_group,
)
from research_classification.hierarchy import audit_encoding, validate_bridge, validate_canonical

DATA_DIR = build_registry.DATA_DIR


def main() -> None:
    print("1. Building canonical FOR/SEO tables...")
    for_df, seo_df = build_for_seo.run()
    validate_canonical(for_df, 23 + 213 + 1967, "FOR")
    validate_canonical(seo_df, 19 + 128 + 840, "SEO")

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

    print("5. Building Leiden bridges (wikipedia_url exact join + empirical derivation)...")
    build_leiden.run()

    print("6. Building ABS FOR2008<->2020 / SEO2008<->2020 correspondence bridges...")
    build_correspondences_abs.run()

    print("7. Building legacy FOR1998/SEO1998 bridges (via direct 1297.0 combined table)...")
    build_correspondences_legacy.run()

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

    print("11. Loading everything into data/research_classification.duckdb...")
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
