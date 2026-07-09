"""Demo: map (year, hep_code, hep_name, state, Category, $K)-style rows -- e.g. from a
HERDC/National Competitive Grants Register extract -- onto a Leiden Ranking Main Field.

This is meant as a template for "other analytical projects": it only reads
data/research_classification.duckdb (copy that one file wherever you need it) and doesn't
import the research_classification package at all.

Why this needs two hops, not one:
  "Category" values like "Medical and health sciences" are pre-2008 broad Field-of-Research
  groupings (ASRC 1998 / RFCD-style division names) -- they don't appear verbatim anywhere
  in ANZSRC 2020, so there's no official crosswalk to look them up in directly. This demo
  fuzzy-matches Category against the 23 FOR2020 division labels (the closest thing we do
  have a real, ABS-published lineage for back to 1998 -- see bridge_asrc1998_for2020.csv),
  then follows the empirically-derived Leiden<->FOR bridge from there. Every other lookup
  in this pipeline is an exact/official match; this free-text hop is the one genuinely
  approximate step, so its score is surfaced rather than hidden.

If your dataset only has a small fixed set of Category values (ASRC 1998 had ~20 divisions),
the practical move is to run this once, eyeball the top candidates below, and save the
result as your own small verified lookup table rather than re-fuzzy-matching every row.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "research_classification.duckdb"

SAMPLE_ROWS = [
    # year, hep_code, hep_name, state, category, amount_k
    (2000, 3004, "Western Sydney University", "NSW", "Medical and health sciences", 3810),
    (2000, 3004, "Western Sydney University", "NSW", "Information, computing and communication sciences", 512),
    (2001, 1001, "University of Sydney", "NSW", "Biological sciences", 9120),
    (2001, 1001, "University of Sydney", "NSW", "Studies in human society", 640),
]


def best_for_division(con: duckdb.DuckDBPyConnection, category: str, top_n: int = 3):
    """Fuzzy-match free-text Category against the 23 FOR2020 division labels."""
    divisions = con.execute("SELECT code, label FROM for_2020 WHERE level = 'division'").fetchall()
    scored = sorted(
        ((code, label, difflib.SequenceMatcher(None, category.lower(), label.lower()).ratio())
         for code, label in divisions),
        key=lambda t: t[2], reverse=True,
    )
    return scored[:top_n]


def leiden_main_field_for_division(con: duckdb.DuckDBPyConnection, for_code: str):
    """FOR division -> Leiden main field, using for2020_division_leiden_main_field.csv.

    This is deliberately NOT an inversion of bridge_leiden_for.csv (which answers the
    opposite question -- "given a Leiden main field, which single division best represents
    it" -- and its low confidence for broad main fields like Social sciences and humanities
    reflects that parent's breadth across many divisions, not doubt about any one division's
    placement). Since FOR divisions are the finer/child level relative to Leiden's main
    fields, the correctly-directed statistic is division-centric: of THIS division's own
    content, what share sits under each Leiden main field. That's what this table holds,
    and it's why e.g. Human Society lands at ~95% here rather than the 43% you'd get by
    naively inverting the other table.
    """
    row = con.execute(
        """
        SELECT leiden_main_field_label, share
        FROM for2020_division_leiden_main_field
        WHERE for_division_code = ? AND is_primary = 'True'
        """,
        [for_code],
    ).fetchone()
    return row  # (leiden_label, share) or None


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print(f"{'year':>4} {'hep':>5} {'hep_name':<26} {'st':<3} {'category':<32} {'$K':>7}"
          f"  ->  {'FOR division (score)':<42}  ->  Leiden main field (confidence)")
    print("-" * 150)

    for year, hep_code, hep_name, state, category, amount_k in SAMPLE_ROWS:
        candidates = best_for_division(con, category)
        for_code, for_label, score = candidates[0]
        leiden = leiden_main_field_for_division(con, for_code)
        leiden_desc = f"{leiden[0]} ({float(leiden[1]):.2f})" if leiden else "no Leiden mapping found"

        print(f"{year:>4} {hep_code:>5} {hep_name:<26} {state:<3} {category:<32} {amount_k:>7}"
              f"  ->  {for_label} [{for_code}] ({score:.2f})"
              f"  ->  {leiden_desc}")

        if len(candidates) > 1 and candidates[1][2] > score - 0.1:
            alts = ", ".join(f"{lbl} ({s:.2f})" for _, lbl, s in candidates[1:])
            print(f"       (close alternate FOR division match(es), worth eyeballing: {alts})")

    print(
        "\nNote: the FOR-division match score is the only approximate step here -- "
        "everything downstream of it (FOR -> Leiden) uses the pipeline's exact/official "
        "or empirically-derived bridges, same as every other lookup in this project."
    )


if __name__ == "__main__":
    main()
