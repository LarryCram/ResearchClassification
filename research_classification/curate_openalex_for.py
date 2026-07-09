"""The one hand-curated table in the pipeline: OpenAlex field (26) -> FOR division (23).

There is no shared provenance between ANZSRC and OpenAlex/ASJC, so this leg cannot be
derived from an exact join or official crosswalk the way every other bridge in this
pipeline is. The primary/alternate picks below are Claude's own judgment, made by reading
each OpenAlex field's actual subfield composition (data/openalex_subfields.csv) against the
FOR division titles. Each row's `confidence` is NOT that subjective judgment restated as a
number -- it's an independently computed bag-of-words overlap score between the field's own
subfield labels and the target division's official ABS Table 4 definition/exclusions text,
so a weak or surprising assignment is visible in the audit output without requiring anyone
to re-read the whole table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import io as rio
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"
FOR_XLSX = ROOT / "data_untracked" / "ABS_FOR_SEO" / "anzsrc2020_for.xlsx"

STOPWORDS = {
    "the", "and", "of", "in", "for", "to", "a", "an", "or", "on", "with", "by", "is",
    "as", "this", "division", "group", "covers", "includes", "it", "other", "not",
    "elsewhere", "classified", "sciences", "science", "studies", "excl", "incl",
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    # crude 5-char-prefix stemming so related word forms match (chemistry/chemical,
    # biology/biological, psychology/psychological) without pulling in a stemmer dependency
    return {w[:5] for w in words if w not in STOPWORDS and len(w) > 2}


def overlap_score(a_text: str, b_text: str) -> float:
    a, b = _tokenize(a_text), _tokenize(b_text)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# Claude's primary/alternate judgment, one or more rows per OpenAlex field code.
# (field_code, for_division_code, is_primary)
CURATION: list[tuple[str, str, bool]] = [
    ("11", "30", True), ("11", "31", False),   # Agricultural and Biological Sciences
    ("12", "43", True), ("12", "36", False), ("12", "50", False), ("12", "47", False),  # Arts and Humanities
    ("13", "31", True), ("13", "32", False),   # Biochemistry, Genetics and Molecular Biology
    ("14", "35", True),                        # Business, Management and Accounting
    ("15", "40", True),                        # Chemical Engineering
    ("16", "34", True),                        # Chemistry
    ("17", "46", True),                        # Computer Science
    ("18", "49", True), ("18", "35", False),   # Decision Sciences
    ("19", "37", True),                        # Earth and Planetary Sciences
    ("20", "38", True),                        # Economics, Econometrics and Finance
    ("21", "40", True), ("21", "41", False),   # Energy
    ("22", "40", True), ("22", "33", False),   # Engineering
    ("23", "41", True),                        # Environmental Science
    ("24", "31", True), ("24", "32", False),   # Immunology and Microbiology
    ("25", "40", True), ("25", "51", False),   # Materials Science
    ("26", "49", True),                        # Mathematics
    ("27", "32", True), ("27", "42", False),   # Medicine
    ("28", "32", True),                        # Neuroscience
    ("29", "42", True),                        # Nursing
    ("30", "32", True),                        # Pharmacology, Toxicology and Pharmaceutics
    ("31", "51", True),                        # Physics and Astronomy
    ("32", "52", True),                        # Psychology
    ("33", "44", True), ("33", "39", False), ("33", "48", False), ("33", "33", False),  # Social Sciences
    ("34", "30", True),                        # Veterinary
    ("35", "42", True),                        # Dentistry
    ("36", "42", True),                        # Health Professions
]


def _field_texts() -> dict[str, str]:
    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    merged = subfields.merge(
        fields[["code", "label"]], left_on="parent_code", right_on="code", suffixes=("_sub", "_field")
    )
    texts: dict[str, str] = {}
    for code, grp in merged.groupby("parent_code"):
        field_label = grp["label_field"].iloc[0]
        texts[code] = field_label + " " + " ".join(grp["label_sub"])
    return texts


def _division_texts() -> dict[str, str]:
    """Division text = the division's own definition PLUS every child group's label and
    definition, so the comparison corpus has vocabulary at the same granularity as the
    OpenAlex subfield labels it's being compared against (a bare one-line division
    definition is too terse to match against on its own)."""
    defs = rio.read_definitions(FOR_XLSX, sheet_name="Table 4")
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    divs = defs[defs["level"] == "division"].set_index("code")
    groups = defs[defs["level"] == "group"]
    group_parent = dict(zip(for_df[for_df["level"] == "group"]["code"], for_df[for_df["level"] == "group"]["parent_code"]))
    texts: dict[str, str] = {}
    for code, row in divs.iterrows():
        texts[code] = f"{row['label']} {row['definition']}"
    for _, row in groups.iterrows():
        parent = group_parent.get(row["code"])
        if parent in texts:
            texts[parent] += f" {row['label']} {row['definition']}"
    return texts


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_field_to_for_division.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    field_label = dict(zip(fields["code"], fields["label"]))
    div_label = dict(zip(for_df[for_df["level"] == "division"]["code"], for_df[for_df["level"] == "division"]["label"]))

    field_texts = _field_texts()
    division_texts = _division_texts()

    rows = []
    for field_code, div_code, is_primary in CURATION:
        score = overlap_score(field_texts.get(field_code, ""), division_texts.get(div_code, ""))
        # sanity check: is this the top-scoring division for this field algorithmically?
        all_scores = {
            dc: overlap_score(field_texts.get(field_code, ""), dt) for dc, dt in division_texts.items()
        }
        top_div = max(all_scores, key=all_scores.get)
        agrees = top_div == div_code
        rows.append(
            {
                "openalex_field_id": field_code,
                "openalex_field_name": field_label.get(field_code, ""),
                "for_division_code": div_code,
                "for_division_label": div_label.get(div_code, ""),
                "is_primary": is_primary,
                "confidence": round(score, 3),
                "notes": (
                    "keyword-overlap self-check agrees with top algorithmic candidate"
                    if agrees
                    else f"keyword-overlap self-check top candidate was division {top_div} "
                    f"({div_label.get(top_div, '')}, score={all_scores[top_div]:.3f}); "
                    "kept Claude's judgment based on subfield composition"
                ),
            }
        )
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
                "source_code": r["openalex_field_id"],
                "source_label": r["openalex_field_name"],
                "system": "FOR",
                "canonical_code": r["for_division_code"],
                "canonical_label": r["for_division_label"],
                "canonical_level": "division",
                "is_primary": str(r["is_primary"]) in ("True", "true", "1"),
                "match_method": "manual_curated",
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(seed.to_string())
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for.csv", ["source_code"])
    print("\nbridge rows:", len(bridge))
    disagreements = seed[seed["notes"].str.contains("top candidate was")]
    print(f"\n{len(disagreements)}/{len(seed)} rows where algorithmic check disagreed with judgment:")
    print(disagreements[["openalex_field_name", "for_division_label", "confidence"]].to_string())
