"""OpenAlex subfield (252) -> FOR group (213). The second (and, unlike the field-to-division
seed, algorithmic rather than hand-reviewed) curated table in the pipeline.

Why this is tractable where a blind 252x213 comparison wouldn't be: every OAX subfield has a
known parent field, and every field is already curated to one or more FOR divisions in
seeds/openalex_field_to_for_division.csv. So for a given subfield, the candidate group pool
is restricted to only the groups belonging to its parent field's already-assigned
division(s) -- ~9 groups on average, occasionally ~20-35 for fields with several division
alternates (e.g. "Arts and Humanities") -- never the full 213. That constrained pool is
small and hierarchically consistent enough that keyword-overlap scoring alone is reliable
enough to BE the curation mechanism here, not just a sanity check on it (see _group_score()
below for why this uses Jaccard + an "Other X" penalty rather than the field-level seed's
min-normalized overlap_score -- that formula turned out to systematically favor every
division's minimal "not elsewhere classified" catch-all group). Confidence is that raw
score; there is no separate manual override list the way the field-level seed has one,
since 252 individual judgment calls isn't practical the way 26 was.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import io as rio
from .curate_openalex_for import STOPWORDS
from .hierarchy import BRIDGE_COLUMNS, write_csv


def _tokenize_with_bigrams(text: str) -> set[str]:
    """Unigram stems PLUS bigrams of consecutive surviving stems. Unigrams alone are prone
    to spurious matches on common cross-domain words ("systems", "development", "rural",
    "analysis" -- none stoplisted, all near-meaningless individually) that coincidentally
    outvote a genuinely on-topic match with fewer but more specific shared words (verified
    directly: "Forestry" matched "Agriculture, land and farm management" via {rural, agric,
    systems, development, analysis} -- 5 generic hits -- over the obviously-correct "Forestry
    sciences" group's 2 specific hits {agroforestry, forest(ry)}). A true topical match tends
    to share not just isolated words but the *phrases* they sit in; unrelated texts sharing a
    handful of common words almost never share the word-pairs around them. Bigrams make that
    distinction visible to Jaccard without a stoplist arms race against every generic word
    that might show up in a scientific abstract.
    """
    words = re.findall(r"[a-z]+", text.lower())
    stems = [w[:5] for w in words if w not in STOPWORDS and len(w) > 2]
    unigrams = set(stems)
    bigrams = {f"{a}_{b}" for a, b in zip(stems, stems[1:])}
    return unigrams | bigrams


def _name_score(name_a: str, name_b: str) -> float:
    a, b = _tokenize_with_bigrams(name_a), _tokenize_with_bigrams(name_b)
    return len(a & b) / len(a | b) if a and b else 0.0


def _group_score(
    subfield_name: str, subfield_text: str, group_code: str, group_label: str, group_text: str
) -> float:
    """Overlap coefficient (intersection / min(|a|,|b|)) over unigrams+bigrams, PLUS a
    name-to-name bonus. Three failure modes were found and traded off against each other
    while building this, in order:

    1. Plain Jaccard (intersection/union) systematically favoured every division's minimal
       "Other X not elsewhere classified" group: its tiny definition gives a small union, so
       a single coincidental generic-word match could beat a genuine 10-token match against
       the real target group. Bigrams reduce (not eliminate) this by requiring matching
       *phrases*, not just isolated common words ("systems", "rural", "development").
    2. But subfields with short own-text and a genuinely correct target group that happens
       to have a long, detailed definition (e.g. "Equine" vs "Veterinary sciences", whose
       definition enumerates a dozen+ specific veterinary subtopics) then score *worse*
       under Jaccard than a coincidental short-text match, because the union is dominated by
       the correct group's own richness -- the opposite bias from #1. Switching the
       normalization to overlap coefficient (divide by the smaller set, not the union) fixes
       this: it rewards the correct group's detailed text covering the subfield's small
       vocabulary, rather than penalising it for being detailed.
    3. Reintroducing that same short-text bias for the *"Other X"* case specifically, since
       overlap coefficient has the same property plain min-normalization did (see
       curate_openalex_for.py's docstring for the original diagnosis). Bigrams alone don't
       fully close this, so the explicit NEC penalty below stays, at a stronger 0.3x (rather
       than 0.5x) to compensate for overlap coefficient's reintroduced short-text advantage.

    The name-to-name score is a bonus on top (not blended in) for the same reason as before:
    a decisive exact-name match ("Forestry" vs "Forestry sciences") should dominate, but
    pairs with zero name overlap despite being genuinely related ("Equine" vs "Veterinary
    sciences") must fall back to the text score entirely unpenalised. Capped at 1.0.
    """
    name_score = _name_score(subfield_name, group_label)

    text_a, text_b = _tokenize_with_bigrams(subfield_text), _tokenize_with_bigrams(group_text)
    text_score = len(text_a & text_b) / min(len(text_a), len(text_b)) if text_a and text_b else 0.0

    score = min(1.0, text_score + name_score)
    if group_code.endswith("99"):  # ANZSRC's own "not elsewhere classified" convention
        score *= 0.3
    return score

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"
FOR_XLSX = ROOT / "data_untracked" / "ABS_FOR_SEO" / "anzsrc2020_for.xlsx"


def _group_texts(for_df: pd.DataFrame) -> dict[str, str]:
    """Group text = the group's own Table 4 definition PLUS every child FIELD's label, for
    the same reason division text included child group labels: a bare group definition is
    too terse to match subfield-level vocabulary against on its own."""
    defs = rio.read_definitions(FOR_XLSX, sheet_name="Table 4")
    groups = defs[defs["level"] == "group"].set_index("code")
    fields = for_df[for_df["level"] == "field"]
    texts: dict[str, str] = {code: f"{row['label']} {row['definition']}" for code, row in groups.iterrows()}
    for _, row in fields.iterrows():
        parent = row["parent_code"]
        if parent in texts:
            texts[parent] += f" {row['label']}"
    return texts


def _subfield_texts(subfields: pd.DataFrame, topics: pd.DataFrame) -> dict[str, str]:
    """Subfield text = the subfield's own label PLUS every child topic's label, the same
    pattern used for field text (field label + child subfield labels) in the field seed."""
    texts: dict[str, str] = dict(zip(subfields["code"], subfields["label"]))
    for _, row in topics.iterrows():
        parent = row["parent_code"]
        if parent in texts:
            texts[parent] += f" {row['label']}"
    return texts


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_subfield_to_for_group.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    field_to_division = pd.read_csv(SEEDS_DIR / "openalex_field_to_for_division.csv", dtype=str, keep_default_na=False)

    group_label = dict(zip(for_df[for_df["level"] == "group"]["code"], for_df[for_df["level"] == "group"]["label"]))
    groups_by_division: dict[str, list[str]] = {}
    for _, row in for_df[for_df["level"] == "group"].iterrows():
        groups_by_division.setdefault(row["parent_code"], []).append(row["code"])

    candidate_divisions_by_field: dict[str, list[str]] = {}
    for field_id, grp in field_to_division.groupby("openalex_field_id"):
        candidate_divisions_by_field[field_id] = list(grp["for_division_code"])

    group_texts = _group_texts(for_df)
    subfield_texts = _subfield_texts(subfields, topics)

    all_group_codes = list(group_label)

    rows = []
    skipped = []
    for _, sub in subfields.iterrows():
        subfield_id, subfield_name, field_id = sub["code"], sub["label"], sub["parent_code"]
        divisions = candidate_divisions_by_field.get(field_id, [])
        candidate_groups = {g for d in divisions for g in groups_by_division.get(d, [])}

        # Escape hatch: the parent field's own curated division(s) sometimes don't include
        # the division holding an otherwise decisive, near-exact-name match -- e.g. "Nutrition
        # and Dietetics" was only searched within Division 42 (its field's assigned division),
        # missing the identically-named Group 3210 that happens to sit in Division 32. A
        # cross-division search restricted to only *decisive* name matches (>=0.5, i.e. most
        # of the name's own tokens overlap) can't reintroduce the coincidental-match problem
        # this whole scoring scheme exists to avoid, since it ignores the constrained pool's
        # bag-of-words text entirely and only fires on genuine, close-to-exact naming.
        exact_name_matches = {g for g in all_group_codes if _name_score(subfield_name, group_label[g]) >= 0.5}
        candidate_groups |= exact_name_matches
        candidate_groups = sorted(candidate_groups)

        if not candidate_groups:
            skipped.append(subfield_id)
            continue

        scored = sorted(
            (
                (g, _group_score(subfield_name, subfield_texts.get(subfield_id, ""), g, group_label.get(g, ""), group_texts.get(g, "")))
                for g in candidate_groups
            ),
            key=lambda t: t[1], reverse=True,
        )
        for i, (group_code, score) in enumerate(scored):
            rows.append(
                {
                    "openalex_subfield_id": subfield_id,
                    "openalex_subfield_name": subfield_name,
                    "for_group_code": group_code,
                    "for_group_label": group_label.get(group_code, ""),
                    "is_primary": i == 0,
                    "confidence": round(score, 3),
                    "notes": f"constrained to groups within division(s) {','.join(divisions)}",
                }
            )

    if skipped:
        print(f"  [openalex_subfield_to_for_group] {len(skipped)} subfield(s) skipped, "
              f"no reachable FOR group (parent field has no division in the seed): {skipped}")

    df = pd.DataFrame(rows)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(seed_path, index=False, encoding="utf-8")
    return df


def to_bridge(seed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in seed.iterrows():
        rows.append(
            {
                "source_system": "OpenAlex",
                "source_code": r["openalex_subfield_id"],
                "source_label": r["openalex_subfield_name"],
                "system": "FOR",
                "canonical_code": r["for_group_code"],
                "canonical_label": r["for_group_label"],
                "canonical_level": "group",
                "is_primary": str(r["is_primary"]) in ("True", "true", "1"),
                "match_method": "constrained_lexical",
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(f"seed rows: {len(seed)}, unique subfields covered: {seed['openalex_subfield_id'].nunique()} / 252")
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for_group.csv", ["source_code"])
    print("bridge rows:", len(bridge))
