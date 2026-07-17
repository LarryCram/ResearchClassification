from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
LEIDEN_DIR = ROOT / "data_untracked" / "classification_openalex_2023nov"
DATA_DIR = ROOT / "research_classification" / "data"

# The raw main_field.tsv numbers 1=SSH, 2=BHS, 3=PSE, 4=LES, 5=MCS. We renumber to match the
# user's own leiden_idx convention (1=MCS, 2=PSE, 3=LES, 4=BHS, 5=SSH) -- the exact reverse --
# applied to both main_field's own code and micro_cluster_main_field's main_field_id so every
# downstream join in this module (which matches on that id) still lines up.
_MAIN_FIELD_ID_REMAP = {"1": "5", "2": "4", "3": "2", "4": "3", "5": "1"}


def load_main_field() -> pd.DataFrame:
    df = pd.read_csv(LEIDEN_DIR / "main_field.tsv", sep="\t", dtype=str, encoding="utf-8")
    df = df.rename(columns={"main_field_id": "code", "main_field": "label"})
    df["code"] = df["code"].replace(_MAIN_FIELD_ID_REMAP)
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
    df["main_field_id"] = df["main_field_id"].replace(_MAIN_FIELD_ID_REMAP)
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


def explode_for_divisions(joined: pd.DataFrame, division_field_seed: pd.DataFrame) -> pd.DataFrame:
    """Attach a FOR2020 division to each joined micro-cluster/topic row, via the
    independently hand-curated FOR2020 division -> OAX field mapping
    (curate_for2020_to_openalex.py), not the reverse (OAX field -> FOR division) seed used
    elsewhere in this pipeline -- using the reverse seed here would make this "FOR2020 ->
    Leiden" derivation circular (deriving evidence FOR the very relationship it's supposed to
    independently confirm), exactly the problem this replaced. Division 45 (Indigenous
    Studies) has no row here by construction (curate_for2020_to_openalex excludes it -- see
    that module's docstring); it's resolved via its own dedicated cultural_proxy mechanism
    instead.
    """
    field_to_division = division_field_seed[["openalex_field_id", "for_division_code"]].drop_duplicates()
    exploded = joined.merge(field_to_division, left_on="field_id", right_on="openalex_field_id", how="inner")
    return exploded.rename(columns={"for_division_code": "for_division"})


def explode_for_groups(joined: pd.DataFrame, group_subfield_seed: pd.DataFrame) -> pd.DataFrame:
    """One level finer than explode_for_divisions() -- attaches a FOR2020 group to each
    joined row via the curated FOR2020 group -> OAX subfield mapping. Several FOR2020 groups
    legitimately share the same OAX subfield (e.g. a division's "Other"/NEC catch-all groups
    routinely land on the same general subfield as their siblings) -- a row fans out to all
    of them, honestly, rather than being restricted to one.
    """
    subfield_to_group = group_subfield_seed[["openalex_subfield_id", "for_group_code"]].drop_duplicates()
    exploded = joined.merge(subfield_to_group, left_on="subfield_id", right_on="openalex_subfield_id", how="inner")
    return exploded.rename(columns={"for_group_code": "for_group"})


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
                    "match_method": "derived_empirical",
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

    # for2020_*_openalex_{domain,field,subfield}.csv are NOT built here anymore -- they come
    # from curate_for2020_to_openalex.py's hand-curated, independent mapping (run earlier in
    # build.py). Only FOR2020 -> Leiden is composed here, through THAT curated mapping (not
    # the reverse OAX->FOR seed) so it isn't circular either: for a FOR2020 division/group,
    # find the OAX field/subfield it was curated to, then majority-vote which Leiden
    # main_field that OAX field/subfield's own topics primarily belong to.
    division_field_seed = pd.read_csv(DATA_DIR / "for2020_division_openalex_field.csv", dtype=str, keep_default_na=False)
    exploded = explode_for_divisions(joined, division_field_seed)
    exploded["main_field_id"] = exploded["micro_cluster_id"].map(
        mc_main_field[mc_main_field["is_primary_main_field"]].set_index("micro_cluster_id")["main_field_id"].to_dict()
    )
    division_to_leiden = division_centric_target(
        for_df, exploded, "main_field_id", main_field_label, "leiden_main_field_id", "leiden_main_field_label"
    )
    write_csv(division_to_leiden, DATA_DIR / "for2020_division_leiden_main_field.csv", ["for_division_code"])

    group_subfield_seed = pd.read_csv(DATA_DIR / "for2020_group_openalex_subfield.csv", dtype=str, keep_default_na=False)
    group_exploded = explode_for_groups(joined, group_subfield_seed)
    group_exploded["main_field_id"] = group_exploded["micro_cluster_id"].map(
        mc_main_field[mc_main_field["is_primary_main_field"]].set_index("micro_cluster_id")["main_field_id"].to_dict()
    )
    group_to_leiden = division_centric_target(
        for_df, group_exploded, "main_field_id", main_field_label, "leiden_main_field_id", "leiden_main_field_label",
        for_level_col="for_group", for_level_name="group",
    )
    write_csv(group_to_leiden, DATA_DIR / "for2020_group_leiden_main_field.csv", ["for_group_code"])

    return {
        "leiden_main_field": main_field,
        "bridge_leiden_openalex_topic": topic_bridge,
        "bridge_leiden_openalex_domain": domain_bridge,
        "bridge_leiden_for": for_bridge,
        "for2020_division_leiden_main_field": division_to_leiden,
        "for2020_group_leiden_main_field": group_to_leiden,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df))
