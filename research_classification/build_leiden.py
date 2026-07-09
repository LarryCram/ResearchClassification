from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
LEIDEN_DIR = ROOT / "data_untracked" / "classification_openalex_2023nov"
DATA_DIR = ROOT / "data"


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
    oax = openalex_raw[["topic_id", "topic_name", "wikipedia_url", "field_id", "domain_id"]]
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


def division_centric_leiden_parent(
    for_df: pd.DataFrame,
    mc_main_field: pd.DataFrame,
    joined_with_for: pd.DataFrame,
    main_field_label: dict[str, str],
) -> pd.DataFrame:
    """The correctly-directed counterpart to bridge_leiden_for.csv. That table answers
    'given a Leiden main field, which single FOR division best represents it' -- and its
    vote-share confidence is honestly low for broad main fields like Social sciences and
    humanities, because one coarse bucket (5 main fields) necessarily contains many
    divisions (23) worth of content; that low share reflects the parent's breadth, not
    doubt about any individual child's placement.

    This function asks the reverse, hierarchically correct question instead: of a given
    FOR division's OWN content, what fraction sits under each Leiden main field? Since FOR
    divisions are the finer/child level relative to Leiden's main fields, this is the
    direction where "confidence" means "is this child's parent correct" -- and it is
    typically high (e.g. Human Society -> Social sciences and humanities is 95%, not 43%).
    """
    primary_main = mc_main_field[mc_main_field["is_primary_main_field"]].set_index(
        "micro_cluster_id"
    )["main_field_id"].to_dict()
    df = joined_with_for.copy()
    df["main_field_id"] = df["micro_cluster_id"].map(primary_main)
    df = df.dropna(subset=["for_division", "main_field_id"])

    for_label = dict(zip(for_df["code"], for_df["label"]))
    rows = []
    for div_code, grp in df.groupby("for_division"):
        counts = grp["main_field_id"].value_counts()
        total = len(grp)
        for i, (mf_code, n) in enumerate(counts.items()):
            rows.append(
                {
                    "for_division_code": div_code,
                    "for_division_label": for_label.get(div_code, ""),
                    "leiden_main_field_id": mf_code,
                    "leiden_main_field_label": main_field_label.get(mf_code, ""),
                    "is_primary": i == 0,
                    "share": round(n / total, 3),
                    "n_micro_clusters": total,
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
    division_parent = division_centric_leiden_parent(
        for_df, mc_main_field, joined_with_for, main_field_label
    )
    write_csv(division_parent, DATA_DIR / "for2020_division_leiden_main_field.csv", ["for_division_code"])

    return {
        "leiden_main_field": main_field,
        "bridge_leiden_openalex_topic": topic_bridge,
        "bridge_leiden_openalex_domain": domain_bridge,
        "bridge_leiden_for": for_bridge,
        "for2020_division_leiden_main_field": division_parent,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df))
