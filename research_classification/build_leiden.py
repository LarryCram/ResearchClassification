from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
LEIDEN_DIR = ROOT / "data_untracked" / "classification_openalex_2023nov"
DATA_DIR = ROOT / "research_classification" / "data"


def load_main_field() -> pd.DataFrame:
    df = pd.read_csv(LEIDEN_DIR / "main_field.tsv", sep="\t", dtype=str, encoding="utf-8")
    df = df.rename(columns={"main_field_id": "code", "main_field": "label"})
    df["level"] = "main_field"
    df["parent_code"] = ""
    return df[["code", "level", "label", "parent_code"]]


def load_micro_clusters() -> pd.DataFrame:
    # micro_cluster.tsv is Windows-1252, not UTF-8 (confirmed: raw UTF-8 read crashes on a
    # real en-dash byte 0x96) -- must be read with the correct source encoding.
    rows = []
    with open(LEIDEN_DIR / "micro_cluster.tsv", encoding="cp1252", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            url = (row.get("wikipedia_url") or "").strip().rstrip("/")
            rows.append({"micro_cluster_id": row["micro_cluster_id"], "wikipedia_url": url})
    return pd.DataFrame(rows)


def load_micro_cluster_main_field() -> pd.DataFrame:
    df = pd.read_csv(
        LEIDEN_DIR / "micro_cluster_main_field.tsv", sep="\t", dtype=str, encoding="utf-8"
    )
    df["is_primary_main_field"] = df["is_primary_main_field"].astype(str).isin(["1", "True", "true"])
    return df


def build_topic_join(micro_clusters: pd.DataFrame, openalex_raw: pd.DataFrame) -> pd.DataFrame:
    """Exact join on wikipedia_url between Leiden micro-clusters and OpenAlex topics.

    ~630 wikipedia_urls are reused across multiple distinct clusters on *each* side (a
    broad page like "Ageing" is the closest Wikipedia match for several genuinely different
    clusters). A plain merge on those would fan out into spurious N:M pairings that aren't
    real correspondences, so only URLs that are unique on both sides are joined -- keeping
    every row in the resulting bridge an unambiguous, truly exact 1:1 match.
    """
    oax = openalex_raw[["topic_id", "topic_name", "wikipedia_url", "field_id", "subfield_id", "domain_id"]]
    oax = oax[oax["wikipedia_url"] != ""]
    oax_unique = oax[~oax.duplicated("wikipedia_url", keep=False)]

    mc = micro_clusters[micro_clusters["wikipedia_url"] != ""]
    mc_unique = mc[~mc.duplicated("wikipedia_url", keep=False)]

    joined = mc_unique.merge(oax_unique, on="wikipedia_url", how="inner")
    return joined


def bridge_topic(joined: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in joined.iterrows():
        rows.append(
            {
                "source_system": "Leiden",
                "source_code": r["micro_cluster_id"],
                "source_label": "",
                "system": "OAX",
                "canonical_code": r["topic_id"],
                "canonical_label": r["topic_name"],
                "canonical_level": "topic",
                "is_primary": True,
                "match_method": "exact_key_join",
                "confidence": 1.0,
                "notes": "exact wikipedia_url match between micro_cluster and OpenAlex topic",
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


def _majority_vote(
    main_field: pd.DataFrame,
    mc_main_field: pd.DataFrame,
    joined: pd.DataFrame,
    target_col: str,
    canonical_lookup: dict[str, tuple[str, str]],
    system: str,
    canonical_level: str,
) -> pd.DataFrame:
    """For each Leiden main_field, take its primary micro-clusters, join each to its
    OpenAlex topic (via `joined`), and take the majority `target_col` value as the primary
    canonical link. confidence = the winning share of joined (non-null) votes."""
    primary_mc = mc_main_field[mc_main_field["is_primary_main_field"]]
    topic_target = joined.set_index("micro_cluster_id")[target_col].to_dict()

    rows = []
    for _, mf in main_field.iterrows():
        mf_code, mf_label = mf["code"], mf["label"]
        mc_ids = primary_mc.loc[primary_mc["main_field_id"] == mf_code, "micro_cluster_id"]
        votes = [topic_target[mc] for mc in mc_ids if mc in topic_target]
        if not votes:
            continue
        counts = pd.Series(votes).value_counts()
        total = len(votes)
        for i, (target_code, n) in enumerate(counts.items()):
            canonical_label, level = canonical_lookup.get(target_code, ("", canonical_level))
            rows.append(
                {
                    "source_system": "Leiden",
                    "source_code": mf_code,
                    "source_label": mf_label,
                    "system": system,
                    "canonical_code": target_code,
                    "canonical_label": canonical_label,
                    "canonical_level": level,
                    "is_primary": i == 0,
                    "match_method": "derived_empirical",
                    "confidence": round(n / total, 3),
                    "notes": f"majority vote over {total} primary micro-clusters joined via OpenAlex topic",
                }
            )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


def explode_for_divisions(joined: pd.DataFrame, bridge_openalex_for: pd.DataFrame) -> pd.DataFrame:
    """Attach FOR division(s) to each joined micro-cluster/topic row, using EVERY
    (openalex_field, for_division) pair from the curated seed -- not just each field's
    primary. Using primary-only here misses 6 of 23 FOR divisions entirely (33, 36, 39, 47,
    48, 50): those divisions were only ever curated as a *secondary* interpretation of a
    broader OpenAlex field (e.g. division 36 Creative Arts is an alternate under field 12
    Arts and Humanities, whose primary is division 43 History), so no row would ever get
    for_division=36 under a primary-only join and any downstream aggregation would silently
    have zero data for it. Using all seed rows means a row can now contribute evidence to
    more than one division (honest, since e.g. an "Arts and Humanities" topic genuinely is
    relevant to History AND Creative Arts AND Philosophy AND Language, not just one of
    them) -- one exception remains: division 45 (Indigenous Studies) has NO row in the seed
    at all, primary or alternate, because none of OpenAlex/ASJC's 26 broad fields has an
    Indigenous-studies equivalent. That's a genuine, real gap (see README-style docstring on
    resolve_forward in resolver.py), not something this exploded join can paper over.
    """
    field_to_divisions = bridge_openalex_for[["source_code", "canonical_code"]].drop_duplicates()
    exploded = joined.merge(field_to_divisions, left_on="field_id", right_on="source_code", how="inner")
    return exploded.rename(columns={"canonical_code": "for_division"}).drop(columns=["source_code"])


def explode_for_groups(joined: pd.DataFrame, bridge_openalex_for_group: pd.DataFrame) -> pd.DataFrame:
    """One level finer than explode_for_divisions(), but PRIMARY-ONLY rather than every
    candidate -- deliberately different from that function's all-alternates approach. The
    division-level seed (26 fields) has few alternates per field, so exploding on all of
    them fills real coverage gaps without much distortion. The group-level seed (252
    subfields, each scored against ~9-30 candidate groups) routinely has several
    close-scoring alternates per subfield; exploding on all of them means a single dominant
    subfield's full micro-cluster count gets duplicated identically across every one of its
    candidate groups (verified directly: groups 4904 and 4905 both showed exactly 123 rows
    -- the field's entire count -- because one subfield's seed row listed both as
    alternates). Primary-only avoids that duplication and gives each group its own honest,
    non-inflated count, at the cost of lower coverage (~129/213 groups vs ~193/213 with
    alternates). That's an acceptable trade: callers (see resolver.py's
    _resolve_from_for2020_code) already fall back to the division-level table when a group
    has no row here, so an uncovered group degrades gracefully rather than getting a
    distorted answer.
    """
    primary = bridge_openalex_for_group[bridge_openalex_for_group["is_primary"] == "True"]
    subfield_to_groups = primary[["source_code", "canonical_code"]].drop_duplicates()
    exploded = joined.merge(subfield_to_groups, left_on="subfield_id", right_on="source_code", how="inner")
    return exploded.rename(columns={"canonical_code": "for_group"}).drop(columns=["source_code"])


def division_centric_target(
    for_df: pd.DataFrame,
    df_exploded: pd.DataFrame,
    target_col: str,
    target_label: dict[str, str],
    target_id_name: str,
    target_label_name: str,
    for_level_col: str = "for_division",
    for_level_name: str = "division",
) -> pd.DataFrame:
    """The hierarchically correct direction for any Leiden/OAX target coarser than a FOR
    division or group: of a given FOR node's OWN content (weighted by how many distinct
    micro-cluster/topic rows land there), what share sits under each candidate value of
    `target_col`? This is deliberately the reverse of bridge_leiden_for.csv /
    bridge_openalex_for.csv, which both answer "given the coarse parent, which single FOR
    division best represents it" -- a question whose low vote-share for broad parents
    reflects the parent's breadth, not doubt about any division's placement. Confidence here
    means "is this FOR node's parent correct," and is typically high for a clean taxonomy.

    for_level_col/for_level_name select division- or group-level grouping over the same
    `df_exploded` shape (pass for_level_col="for_group", for_level_name="group" for the
    group-centric tables, built from a group-keyed exploded frame instead of division-keyed).
    """
    df = df_exploded.dropna(subset=[for_level_col, target_col])
    for_label = dict(zip(for_df["code"], for_df["label"]))
    rows = []
    for level_code, grp in df.groupby(for_level_col):
        counts = grp[target_col].value_counts()
        total = len(grp)
        for i, (target_code, n) in enumerate(counts.items()):
            rows.append(
                {
                    f"for_{for_level_name}_code": level_code,
                    f"for_{for_level_name}_label": for_label.get(level_code, ""),
                    target_id_name: target_code,
                    target_label_name: target_label.get(target_code, ""),
                    "is_primary": i == 0,
                    "share": round(n / total, 3),
                    "n_rows": total,
                }
            )
    return pd.DataFrame(rows)


def run() -> dict[str, pd.DataFrame]:
    from . import build_openalex

    main_field = load_main_field()
    write_csv(main_field, DATA_DIR / "leiden_main_field.csv", ["code"])

    micro_clusters = load_micro_clusters()
    mc_main_field = load_micro_cluster_main_field()
    openalex_raw = build_openalex.load_raw()

    joined = build_topic_join(micro_clusters, openalex_raw)
    topic_bridge = bridge_topic(joined)
    write_csv(topic_bridge, DATA_DIR / "bridge_leiden_openalex_topic.csv", ["source_code"])

    openalex_fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    openalex_domains = pd.read_csv(DATA_DIR / "openalex_domains.csv", dtype=str, keep_default_na=False)
    field_lookup = dict(zip(openalex_fields["code"], zip(openalex_fields["label"], ["field"] * len(openalex_fields))))
    domain_lookup = dict(zip(openalex_domains["code"], zip(openalex_domains["label"], ["domain"] * len(openalex_domains))))

    domain_bridge = _majority_vote(
        main_field, mc_main_field, joined, "domain_id", domain_lookup, "OAX", "domain"
    )
    write_csv(domain_bridge, DATA_DIR / "bridge_leiden_openalex_domain.csv", ["source_code"])

    bridge_openalex_for = pd.read_csv(DATA_DIR / "bridge_openalex_for.csv", dtype=str, keep_default_na=False)
    bridge_openalex_for["is_primary"] = bridge_openalex_for["is_primary"].isin(["True", "true"])
    for_primary = bridge_openalex_for[bridge_openalex_for["is_primary"]]
    field_to_for = dict(zip(for_primary["source_code"], zip(for_primary["canonical_label"], ["division"] * len(for_primary))))
    field_to_for_code = dict(zip(for_primary["source_code"], for_primary["canonical_code"]))

    joined_with_for = joined.copy()
    joined_with_for["for_division"] = joined_with_for["field_id"].map(field_to_for_code)
    for_lookup = {code: field_to_for.get(fid, ("", "division")) for fid, code in field_to_for_code.items()}

    for_bridge = _majority_vote(
        main_field, mc_main_field, joined_with_for, "for_division", for_lookup, "FOR", "division"
    )
    write_csv(for_bridge, DATA_DIR / "bridge_leiden_for.csv", ["source_code"])

    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    main_field_label = dict(zip(main_field["code"], main_field["label"]))
    field_label_plain = dict(zip(openalex_fields["code"], openalex_fields["label"]))
    domain_label_plain = dict(zip(openalex_domains["code"], openalex_domains["label"]))

    # exploded on EVERY seed row (primary + alternate), not just primary -- see
    # explode_for_divisions()'s docstring for why that matters (6 of 23 divisions would
    # otherwise have zero data). Each row also carries its own primary Leiden main_field.
    exploded = explode_for_divisions(joined, bridge_openalex_for)
    exploded["main_field_id"] = exploded["micro_cluster_id"].map(
        mc_main_field[mc_main_field["is_primary_main_field"]].set_index("micro_cluster_id")["main_field_id"].to_dict()
    )

    division_to_leiden = division_centric_target(
        for_df, exploded, "main_field_id", main_field_label, "leiden_main_field_id", "leiden_main_field_label"
    )
    write_csv(division_to_leiden, DATA_DIR / "for2020_division_leiden_main_field.csv", ["for_division_code"])

    division_to_oax_domain = division_centric_target(
        for_df, exploded, "domain_id", domain_label_plain, "openalex_domain_id", "openalex_domain_label"
    )
    write_csv(division_to_oax_domain, DATA_DIR / "for2020_division_openalex_domain.csv", ["for_division_code"])

    division_to_oax_field = division_centric_target(
        for_df, exploded, "field_id", field_label_plain, "openalex_field_id", "openalex_field_label"
    )
    write_csv(division_to_oax_field, DATA_DIR / "for2020_division_openalex_field.csv", ["for_division_code"])

    openalex_subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    subfield_label_plain = dict(zip(openalex_subfields["code"], openalex_subfields["label"]))
    division_to_oax_subfield = division_centric_target(
        for_df, exploded, "subfield_id", subfield_label_plain, "openalex_subfield_id", "openalex_subfield_label"
    )
    write_csv(division_to_oax_subfield, DATA_DIR / "for2020_division_openalex_subfield.csv", ["for_division_code"])

    # Group-level (4-digit) counterparts of the four division-centric tables above, one
    # level finer, built the identical way but exploded through
    # seeds/openalex_subfield_to_for_group.csv instead of the field->division seed. Coverage
    # is necessarily partial (see explode_for_groups()'s docstring) -- a FOR group with no
    # rows here just doesn't get a row in these tables, which callers must handle by falling
    # back to the division-level table, not something these functions paper over.
    bridge_openalex_for_group = pd.read_csv(DATA_DIR / "bridge_openalex_for_group.csv", dtype=str, keep_default_na=False)
    group_exploded = explode_for_groups(joined, bridge_openalex_for_group)
    group_exploded["main_field_id"] = group_exploded["micro_cluster_id"].map(
        mc_main_field[mc_main_field["is_primary_main_field"]].set_index("micro_cluster_id")["main_field_id"].to_dict()
    )

    group_to_leiden = division_centric_target(
        for_df, group_exploded, "main_field_id", main_field_label, "leiden_main_field_id", "leiden_main_field_label",
        for_level_col="for_group", for_level_name="group",
    )
    write_csv(group_to_leiden, DATA_DIR / "for2020_group_leiden_main_field.csv", ["for_group_code"])

    group_to_oax_domain = division_centric_target(
        for_df, group_exploded, "domain_id", domain_label_plain, "openalex_domain_id", "openalex_domain_label",
        for_level_col="for_group", for_level_name="group",
    )
    write_csv(group_to_oax_domain, DATA_DIR / "for2020_group_openalex_domain.csv", ["for_group_code"])

    group_to_oax_field = division_centric_target(
        for_df, group_exploded, "field_id", field_label_plain, "openalex_field_id", "openalex_field_label",
        for_level_col="for_group", for_level_name="group",
    )
    write_csv(group_to_oax_field, DATA_DIR / "for2020_group_openalex_field.csv", ["for_group_code"])

    group_to_oax_subfield = division_centric_target(
        for_df, group_exploded, "subfield_id", subfield_label_plain, "openalex_subfield_id", "openalex_subfield_label",
        for_level_col="for_group", for_level_name="group",
    )
    write_csv(group_to_oax_subfield, DATA_DIR / "for2020_group_openalex_subfield.csv", ["for_group_code"])

    return {
        "leiden_main_field": main_field,
        "bridge_leiden_openalex_topic": topic_bridge,
        "bridge_leiden_openalex_domain": domain_bridge,
        "bridge_leiden_for": for_bridge,
        "for2020_division_leiden_main_field": division_to_leiden,
        "for2020_division_openalex_domain": division_to_oax_domain,
        "for2020_division_openalex_field": division_to_oax_field,
        "for2020_division_openalex_subfield": division_to_oax_subfield,
        "for2020_group_leiden_main_field": group_to_leiden,
        "for2020_group_openalex_domain": group_to_oax_domain,
        "for2020_group_openalex_field": group_to_oax_field,
        "for2020_group_openalex_subfield": group_to_oax_subfield,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df))
