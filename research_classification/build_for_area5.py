"""FOR2020 division -> 5-area aggregate, user-provided (research_classification/data/raw/
for_areas/FoR_Areas.csv). Plays the same role CWTS Leiden's main_field used to play (a coarse,
top-level grouping above the FOR divisions), but as a direct fact rather than the old indirect
FOR2020 -> OAX -> Leiden derivation loop -- this resolves straight off the division code, the
same way seo2020_division_sdg.csv does today.

Source file has a placeholder Excel-paste header row before the real header, tab-delimited.
Division 45 (Indigenous Studies) and the source's own "MD Multidisciplinary" row are both
present in the raw file; MD is skipped here since FOR2020 itself has no multidisciplinary
catch-all division to attach it to (confirmed against for_2020.csv -- see TODO.md's note on
FOR1998's own now-orphaned general/multidisciplinary divisions for the same reason), and
Indigenous Studies deliberately keeps its own dedicated label rather than folding into one of
the 5 substantive areas, consistent with how division 45 is special-cased elsewhere in this
pipeline (curate_for2020_division45_to_proxy.py).
"""

from __future__ import annotations

import pandas as pd

from .hierarchy import write_csv
from .paths import CANONICAL_DIR, RAW_DIR

SRC = RAW_DIR / "for_areas" / "FoR_Areas.csv"

_AREA_CODES: dict[str, str] = {
    "Life and Earth Science": "LES",
    "Biomedical and Health Science": "BHS",
    "Physical Science and Engineering": "PSE",
    "Social Science and Humanities": "SSH",
    "Mathematics, Computing and Information Science": "MCS",
    "INDIGENOUS STUDIES": "IND",
}


def run() -> pd.DataFrame:
    raw = pd.read_csv(SRC, sep="\t", skiprows=1, dtype=str, keep_default_na=False)

    for_df = pd.read_csv(CANONICAL_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    division_label = dict(zip(
        for_df[for_df["level"] == "division"]["code"], for_df[for_df["level"] == "division"]["label"]
    ))

    rows = []
    skipped = []
    for _, r in raw.iterrows():
        division_code = r["code"].removeprefix("F")
        if division_code not in division_label:
            skipped.append((division_code, r["Areas"]))
            continue
        area_label = r["Areas"].strip()
        rows.append(
            {
                "for2020_division_code": division_code,
                "for2020_division_label": division_label[division_code],
                "area5_code": _AREA_CODES.get(area_label, ""),
                "area5_label": area_label,
                "confidence": 1.0,
                "notes": "user-provided FOR2020 division -> 5-area aggregate",
            }
        )

    if skipped:
        print(f"  [build_for_area5] {len(skipped)} raw row(s) skipped (no matching FOR2020 "
              f"division): {skipped}")

    df = pd.DataFrame(rows)
    assert set(df["for2020_division_code"]) == set(division_label), (
        "for2020_area5.csv does not cover every FOR2020 division: "
        f"missing {sorted(set(division_label) - set(df['for2020_division_code']))}"
    )
    write_csv(df, CANONICAL_DIR / "for2020_area5.csv", ["for2020_division_code"])
    return df


if __name__ == "__main__":
    df = run()
    print("for2020_area5 rows:", len(df))
    print(df.to_string())
