"""FOR2020 division/group -> OAX domain/field/subfield, algorithmic via cascade_match's
topic_rank_resolve() (see that function's docstring for the full rationale: score every
individual OpenAlex topic against the FOR node's field-level bag, rank, and see which OAX
subfield/field the top N concentrate under -- "what a human does" rather than aggregating
everything into one diluted bag first).

Replaces build_leiden.py's previous generation method for these tables
(for2020_division_openalex_{domain,field,subfield}.csv and their for2020_group_ counterparts),
which was NOT independent evidence the way it looked -- it derived a FOR division's OAX field
distribution by looking up which OAX field each of its member topics' micro-clusters belonged
to via bridge_openalex_for.csv, which is itself generated FROM the OAX field -> FOR division
seed. So "division 39 EDUCATION's real empirical OAX subfield" was actually just "which of
whichever single OAX field the hand-typed seed happened to pair with division 39 has the most
topics" -- confirmed directly: it returned subfield 3312 "Sociology and Political Science"
(33.6% share) with 3304 "Education" a distant third (14.3%), because every topic ever
attributed to division 39 got there only by riding along under field 33 "Social Sciences",
division 39's one seed alternate. This script has no such dependency -- it scores FOR2020's
own field-level text directly against OAX's own topic labels, nothing routed through the
field->division seed at all.

Domain and field answers are derived from the SAME topic-ranking pass (not three independent
searches) -- topic_rank_resolve()'s field-level winner supplies both the field-level row and,
via that field's own parent, the domain-level row; its subfield-level winner supplies the
subfield-level row. This keeps all three granularities consistent with one another, backed by
the same underlying evidence.

Leiden is NOT derived here, and never independently -- Leiden has no direct relationship to
FOR2020 at all; it's composed purely from OAX (see curate_openalex_to_leiden.py and
build_leiden.py's composition step).

Division 45 (Indigenous Studies) is excluded -- see curate_for2020_division45_to_proxy.py for
its own dedicated resolution mechanism.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import cascade_match as cm
from .hierarchy import write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"

# Escape hatch, division-level only -- filled in after a direct read-through of the real run
# found topic_rank_resolve() picks that were low-share noise rather than genuine signal (a
# division whose top-30 topics scatter across many subfields with no real concentration
# still returns SOME top pick, and a couple were wrong on inspection: "PHYSICAL SCIENCES"
# landed on OAX field "Engineering" (0.4 share) purely because physics/engineering topics
# share generic vocabulary, when OAX field "Physics and Astronomy" is the obvious answer;
# "HISTORY, HERITAGE AND ARCHAEOLOGY"/"LAW AND LEGAL STUDIES"/"PHILOSOPHY AND RELIGIOUS
# STUDIES" all landed on subfield "Sociology and Political Science"/"Political Science..."
# (0.13-0.17 share, near-noise) when OAX subfields literally named "History"/"Law"/
# "Philosophy" exist and are the obvious answer. Direct correction, not another formula.
# for_division_code -> overrides (any subset of these keys)
_DIVISION_OVERRIDES: dict[str, dict[str, str]] = {
    "51": {"field_code": "31", "field_label": "Physics and Astronomy",
           "subfield_code": "3103", "subfield_label": "Astronomy and Astrophysics"},
    "43": {"subfield_code": "1202", "subfield_label": "History"},
    "48": {"subfield_code": "3308", "subfield_label": "Law"},
    "50": {"subfield_code": "1211", "subfield_label": "Philosophy"},
    "33": {"subfield_code": "2216", "subfield_label": "Architecture"},
    # BIOMEDICAL AND CLINICAL SCIENCES has no single decent subfield -- OAX splits medicine
    # into ~30 discrete clinical specialties with no generic "Medicine" subfield among them,
    # so the algorithm's weak pick (Pediatrics, 0.1 share) is left as-is rather than swapped
    # for an equally-arbitrary alternative; the field-level answer (Medicine, 0.267) is the
    # more trustworthy one for this division regardless.
}


def _exact_match(label: str, source_bag: str, fields_df: pd.DataFrame, subfields_df: pd.DataFrame,
                  field_bags: dict[str, str], subfield_bags: dict[str, str]) -> dict[str, str] | None:
    """Exact word-set match (see cascade_match.exact_match_words) between a FOR2020 node's
    own label and OAX subfield labels first, then field labels -- the same step-1 exact-match
    this whole cascade uses everywhere else, but missing from this direction until found
    directly: FOR2020 group 3301 "Architecture" landed on OAX subfield "History and
    Philosophy of Science" (0.133 share, pure topic-ranking noise) instead of the OAX
    subfield literally named "Architecture" (2216), because topic_rank_resolve() has no
    exact-match short-circuit of its own -- it only ever does per-topic fuzzy ranking. Tried
    at subfield granularity first (finer, and gives the parent field for free); falls back to
    field-level exact match if no subfield matches, then a contains-match pass at each level
    (see cascade_match.contains_match()).

    OAX has several genuinely duplicate-named subfields under two different parent fields
    (Genetics, Physiology, Microbiology, Neurology, Pharmacology, Archeology, Biochemistry --
    found directly via a same-side self-match audit). Multiple hits sharing the identical
    label TEXT are still an exact name match; broken by bag overlap against source_bag rather
    than given up on, the same fix applied in cascade_match.cascade_resolve()."""
    words = cm.exact_match_words(label)
    if not words:
        return None

    def _pick(df: pd.DataFrame, bags: dict[str, str], words_col_words: dict[str, set[str]]) -> pd.Series | None:
        hits = [code for code, w in words_col_words.items() if w == words]
        if len(hits) == 1:
            return df[df["code"] == hits[0]].iloc[0]
        if len(hits) > 1:
            labels = {df[df["code"] == c]["label"].iloc[0] for c in hits}
            if len(labels) == 1:  # genuine same-named duplicate -- break tie by content overlap
                best = max(hits, key=lambda c: cm.bag_overlap(source_bag, bags.get(c, "")))
                return df[df["code"] == best].iloc[0]
        return None

    sub_words = {row["code"]: cm.exact_match_words(row["label"]) for _, row in subfields_df.iterrows()}
    row = _pick(subfields_df, subfield_bags, sub_words)
    if row is not None:
        field_row = fields_df[fields_df["code"] == row["parent_code"]]
        field_label = field_row["label"].iloc[0] if len(field_row) else ""
        return {
            "subfield_code": row["code"], "subfield_label": row["label"],
            "field_code": row["parent_code"], "field_label": field_label,
        }
    field_words = {row["code"]: cm.exact_match_words(row["label"]) for _, row in fields_df.iterrows()}
    row = _pick(fields_df, field_bags, field_words)
    if row is not None:
        return {"field_code": row["code"], "field_label": row["label"]}

    contains_pool_sub = {c: w for c, w in sub_words.items() if not cm.is_nec_code(c)}
    contains_hit = cm.contains_match(words, contains_pool_sub)
    if contains_hit is not None:
        row = subfields_df[subfields_df["code"] == contains_hit].iloc[0]
        field_row = fields_df[fields_df["code"] == row["parent_code"]]
        field_label = field_row["label"].iloc[0] if len(field_row) else ""
        return {
            "subfield_code": row["code"], "subfield_label": row["label"],
            "field_code": row["parent_code"], "field_label": field_label,
        }
    contains_pool_field = {c: w for c, w in field_words.items() if not cm.is_nec_code(c)}
    contains_hit = cm.contains_match(words, contains_pool_field)
    if contains_hit is not None:
        row = fields_df[fields_df["code"] == contains_hit].iloc[0]
        return {"field_code": row["code"], "field_label": row["label"]}
    return None


def _rows_for_level(for_df: pd.DataFrame, bags: dict[str, str], level_name: str,
                     topics: pd.DataFrame, subfields: pd.DataFrame, fields: pd.DataFrame,
                     domain_label: dict[str, str], field_domain: dict[str, str]) -> dict[str, list[dict]]:
    for_label = dict(zip(for_df["code"], for_df["label"]))
    domain_rows, field_rows, subfield_rows = [], [], []
    for code, bag in bags.items():
        label = for_label.get(code, "")

        exact = _exact_match(label, fields, subfields)
        if exact is not None:
            field_code, field_label = exact["field_code"], exact["field_label"]
            subfield_code, subfield_label = exact.get("subfield_code", ""), exact.get("subfield_label", "")
            field_share = subfield_share = 1.0
            n_rows = 0
        else:
            result = cm.topic_rank_resolve(bag, topics, subfields, fields)
            if result is None:
                continue
            field_code, field_label, field_share = result["field_code"], result["field_label"], result["field_share"]
            subfield_code, subfield_label, subfield_share = result["subfield_code"], result["subfield_label"], result["subfield_share"]
            n_rows = result["n_topics_considered"]

        override = _DIVISION_OVERRIDES.get(code, {}) if level_name == "division" else {}
        if "field_code" in override:
            field_code, field_label = override["field_code"], override["field_label"]
        if "subfield_code" in override:
            subfield_code, subfield_label = override["subfield_code"], override.get("subfield_label", "")

        domain_code = field_domain.get(field_code, "")

        domain_rows.append({
            f"for_{level_name}_code": code, f"for_{level_name}_label": label,
            "openalex_domain_id": domain_code, "openalex_domain_label": domain_label.get(domain_code, ""),
            "is_primary": True, "share": field_share, "n_rows": n_rows,
        })
        field_rows.append({
            f"for_{level_name}_code": code, f"for_{level_name}_label": label,
            "openalex_field_id": field_code, "openalex_field_label": field_label,
            "is_primary": True, "share": field_share, "n_rows": n_rows,
        })
        if subfield_code:
            subfield_rows.append({
                f"for_{level_name}_code": code, f"for_{level_name}_label": label,
                "openalex_subfield_id": subfield_code, "openalex_subfield_label": subfield_label,
                "is_primary": True, "share": subfield_share, "n_rows": n_rows,
            })
    return {"domain": domain_rows, "field": field_rows, "subfield": subfield_rows}


def run() -> dict[str, pd.DataFrame]:
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_df = for_df[~for_df["code"].str.startswith("45")]  # division 45 excluded; own proxy mechanism
    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    domains = pd.read_csv(DATA_DIR / "openalex_domains.csv", dtype=str, keep_default_na=False)

    domain_label = dict(zip(domains["code"], domains["label"]))
    field_domain = dict(zip(fields["code"], fields["parent_code"]))

    div_bags = cm.for_division_texts(for_df)
    grp_bags = cm.for_group_texts(for_df)

    div = _rows_for_level(for_df, div_bags, "division", topics, subfields, fields, domain_label, field_domain)
    grp = _rows_for_level(for_df, grp_bags, "group", topics, subfields, fields, domain_label, field_domain)

    tables = {
        "for2020_division_openalex_domain": pd.DataFrame(div["domain"]),
        "for2020_division_openalex_field": pd.DataFrame(div["field"]),
        "for2020_division_openalex_subfield": pd.DataFrame(div["subfield"]),
        "for2020_group_openalex_domain": pd.DataFrame(grp["domain"]),
        "for2020_group_openalex_field": pd.DataFrame(grp["field"]),
        "for2020_group_openalex_subfield": pd.DataFrame(grp["subfield"]),
    }
    for name, df in tables.items():
        key_col = "for_division_code" if "division" in name else "for_group_code"
        write_csv(df, DATA_DIR / f"{name}.csv", [key_col])
    return tables


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df))
    print()
    print(tables["for2020_division_openalex_subfield"].to_string())
