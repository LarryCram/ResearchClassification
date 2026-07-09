"""Demo: map (year, hep_code, hep_name, state, Category, $K)-style rows -- e.g. from a
HERDC/National Competitive Grants Register extract -- forward to FOR2020, OpenAlex (OAX),
and Leiden Ranking Main Field, using research_classification.Resolver.

This is the pattern for any other project: `pip install git+https://github.com/LarryCram/
ResearchClassification.git`, then `Resolver()` -- no separate build step, no data file to
copy around. It loads the CSVs bundled inside the package into an in-memory DuckDB.

Why there's still one manual step before resolve_forward() can run:
  "Category" values like "Medical and health sciences" are pre-2008 broad Field-of-Research
  groupings (ASRC 1998 / RFCD-style division names) written as free text, not a code.
  resolve_forward() (like the rest of this pipeline) only does exact code/label lookups --
  it deliberately never guesses at free text, since a bad silent match is worse than a loud
  failure. So this demo fuzzy-matches Category against the 23 FOR2020 division labels itself
  (the one genuinely approximate step, with its score always shown, run directly against the
  resolver's own connection via `resolver._con`), then hands the resulting FOR2020 division
  *code* to resolve_forward() for everything after that -- which is exact/official or
  empirically-derived the whole way, exactly like every other resolve_forward() call,
  whether or not it started from free text.

If your dataset only has a small fixed set of Category values (ASRC 1998 had ~20 divisions),
the practical move is to run this once, eyeball the top candidates below, and save the
result as your own small verified lookup table rather than re-fuzzy-matching every row.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb

from research_classification import Resolver

SAMPLE_ROWS = [
    # year, hep_code, hep_name, state, category, amount_k
    (2000, 3004, "Western Sydney University", "NSW", "Medical and health sciences", 3810),
    (2000, 3004, "Western Sydney University", "NSW", "Information, computing and communication sciences", 512),
    (2001, 1001, "University of Sydney", "NSW", "Biological sciences", 9120),
    (2001, 1001, "University of Sydney", "NSW", "Studies in human society", 640),
]

# A row can also arrive as an actual RFCD1998 code rather than free text -- resolve_forward()
# handles that directly, no fuzzy-matching step needed at all.
SAMPLE_RFCD1998_CODE = "230104"  # "Category Theory, K Theory, Homological Algebra"


def best_for_division(con: duckdb.DuckDBPyConnection, category: str, top_n: int = 3):
    """The one approximate step: fuzzy-match free-text Category against the 23 FOR2020
    division labels. Everything downstream of this uses resolve_forward()."""
    divisions = con.execute("SELECT code, label FROM for_2020 WHERE level = 'division'").fetchall()
    scored = sorted(
        ((code, label, difflib.SequenceMatcher(None, category.lower(), label.lower()).ratio())
         for code, label in divisions),
        key=lambda t: t[2], reverse=True,
    )
    return scored[:top_n]


def print_forward_result(prefix: str, results: dict) -> None:
    for2020 = results["FOR2020"] if "FOR2020" in results else results["SEO2020"]
    oax, leiden = results["OAX"], results["Leiden"]
    print(f"{prefix}  ->  {for2020.label} [{for2020.code}] ({for2020.confidence:.2f}, {for2020.method})")
    oax_desc = f"{oax.label} [{oax.level}] ({oax.confidence:.2f})" if oax.method != "unavailable" else f"unavailable -- {oax.note}"
    leiden_desc = f"{leiden.label} ({leiden.confidence:.2f})" if leiden.method != "unavailable" else f"unavailable -- {leiden.note}"
    print(f"{'':{len(prefix)}}  ->  OAX: {oax_desc}")
    print(f"{'':{len(prefix)}}  ->  Leiden: {leiden_desc}")


def main() -> None:
    resolver = Resolver()  # loads the bundled CSVs into an in-memory DuckDB, ready immediately

    print("=== Free-text Category column (needs a fuzzy-match step first) ===\n")
    for year, hep_code, hep_name, state, category, amount_k in SAMPLE_ROWS:
        candidates = best_for_division(resolver._con, category)
        for_code, _, score = candidates[0]
        prefix = f"{year} {hep_code} {hep_name:<26} {state} {category!r:<35} ${amount_k}K  (fuzzy match {score:.2f})"

        results = resolver.resolve_forward(for_code, "FOR")
        print_forward_result(prefix, results)

        if len(candidates) > 1 and candidates[1][2] > score - 0.1:
            alts = ", ".join(f"{lbl} ({s:.2f})" for _, lbl, s in candidates[1:])
            print(f"{'':{len(prefix)}}     (close alternate FOR division match(es), worth eyeballing: {alts})")
        print()

    print("=== Actual RFCD1998 code (no fuzzy-matching needed at all) ===\n")
    prefix = f"RFCD1998 {SAMPLE_RFCD1998_CODE!r}"
    print_forward_result(prefix, resolver.resolve_forward(SAMPLE_RFCD1998_CODE, "FOR"))

    print(
        "\nNote: only the Category fuzzy-match above is approximate. Every resolve_forward()"
        " call is exact/official or empirically-derived the whole way -- forward in time only"
        " (never FOR2020 -> FOR2008 -> RFCD1998), and up the hierarchy only (OAX is reported"
        " at field level, never a fabricated guess at one of 4516 topics)."
    )


if __name__ == "__main__":
    main()
