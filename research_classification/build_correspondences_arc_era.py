"""Empirical FOR2008 <-> FOR2020 bridge, derived from ARC ERA's own journal-to-FOR
classifications at two vintages (data/raw/arc_era/australia-era-for.xlsx for FOR2008,
data/raw/arc_era/Australia-era-for-2023.xlsx for FOR2020) -- an independent, journal-based
cross-check against the official ABS correspondence (bridge_for2008_for2020.csv), not a
replacement for it. Deliberately NOT wired into resolver.py's _VINTAGE_BRIDGE_TABLE: this
bridge lives purely as a sibling file for manual comparison against the official one.

Join key: JNL11 (the FOR2008 file's 11-char WoS journal abbreviation) against the FOR2020
file's own `Journal` column, which uses the same abbreviation convention -- verified directly
(not assumed): 10,298 of 16,679 unique FOR2020-file journal labels match (61.7%), covering
10,298 of 11,575 unique FOR2008-file JNL11 values (89%). A real, workable match rate for an
empirical cross-validation bridge, not perfect -- expected given the ARC ERA journal set
drifted between the 2008 and 2023 collection rounds.

Division-level and group-level rows are tallied separately, not mixed: a journal's FOR2008
division-level categories vote only against that same journal's FOR2020 division-level
categories, and likewise at group level. Majority vote per FOR2008 code, same pattern as
build_correspondences_rollup.py's leaf-to-division/group roll-up and build_leiden.py's
Leiden-to-OAX majority vote -- reused, not reinvented.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv
from .paths import BRIDGES_DIR, CANONICAL_DIR, RAW_DIR

FOR2008_XLSX = RAW_DIR / "arc_era" / "australia-era-for.xlsx"
FOR2020_XLSX = RAW_DIR / "arc_era" / "Australia-era-for-2023.xlsx"


def _normalize_journal(name: object) -> str:
    return str(name).strip().upper()


def _load_for2008_journal_codes() -> pd.DataFrame:
    df = pd.read_excel(FOR2008_XLSX, sheet_name="FOR_2018", dtype=str)
    df["journal"] = df["JNL11"].map(_normalize_journal)
    df["code"] = df["code"].str.removeprefix("F")
    df["level"] = df["type"].map({"FOR2": "division", "FOR4": "group"})
    # "MD" (Multidisciplinary) is ARC ERA's own administrative catch-all, not a real ANZSRC
    # FOR2008 division/group -- excluded on both sides (see _load_for2020_journal_codes),
    # same reasoning as build_for_area5.py skipping it (no matching FOR2020 division to
    # attach it to either).
    df = df[df["code"] != "MD"]
    return df[["journal", "code", "level", "fordesc"]]


def _load_for2020_journal_codes() -> pd.DataFrame:
    xl = pd.ExcelFile(FOR2020_XLSX)
    categories = xl.parse("Categories", dtype=str)
    category_to_code = dict(zip(categories["Category"], categories["code"].str.removeprefix("F")))

    journals = xl.parse("Journals", dtype=str)
    journals["journal"] = journals["Journal"].map(_normalize_journal)
    journals["code"] = journals["Category"].map(category_to_code)
    journals = journals.dropna(subset=["code"])
    journals = journals[journals["code"] != "MD"]
    journals["level"] = journals["code"].str.len().map({2: "division", 4: "group"})
    return journals[["journal", "code", "level"]]


def _tally(
    for2008: pd.DataFrame, for2020: pd.DataFrame, level: str, for_canonical_lookup: dict[str, str]
) -> pd.DataFrame:
    """Majority vote: for each FOR2008 code at this level, the FOR2020 code (same level) that
    the largest share of its shared journals' own FOR2020 categories agree on becomes primary;
    confidence is that share."""
    source = for2008[for2008["level"] == level]
    target_votes = for2020[for2020["level"] == level].groupby("journal")["code"].apply(list).to_dict()

    source_label = dict(zip(source["code"], source["fordesc"]))
    journals_by_code: dict[str, list[str]] = {}
    for code, grp in source.groupby("code"):
        journals_by_code[code] = grp["journal"].tolist()

    rows = []
    for code, journals in journals_by_code.items():
        votes = [v for j in journals for v in target_votes.get(j, [])]
        if not votes:
            continue
        counts = Counter(votes)
        total = len(votes)
        for i, (canonical_code, n) in enumerate(counts.most_common()):
            rows.append(
                {
                    "source_system": "FOR2008",
                    "source_code": code,
                    "source_label": source_label.get(code, ""),
                    "system": "FOR",
                    "canonical_code": canonical_code,
                    "canonical_label": for_canonical_lookup.get(canonical_code, ""),
                    "canonical_level": level,
                    "is_primary": i == 0,
                    "match_method": "derived_empirical",
                    "confidence": round(n / total, 3),
                    "notes": f"derived via ARC ERA journal crosswalk: {total} shared-journal "
                             f"vote(s) over {len(journals)} FOR2008-classified journal(s), {n} agreeing",
                }
            )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


def run() -> pd.DataFrame:
    for_df = pd.read_csv(CANONICAL_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_canonical_lookup = dict(zip(for_df["code"], for_df["label"]))

    for2008 = _load_for2008_journal_codes()
    for2020 = _load_for2020_journal_codes()

    division_bridge = _tally(for2008, for2020, "division", for_canonical_lookup)
    group_bridge = _tally(for2008, for2020, "group", for_canonical_lookup)
    bridge = pd.concat([division_bridge, group_bridge], ignore_index=True)

    write_csv(bridge, BRIDGES_DIR / "bridge_for2008_for2020_arc_era.csv", ["source_code"])
    return bridge


if __name__ == "__main__":
    bridge = run()
    print("bridge rows:", len(bridge), "by level:", bridge["canonical_level"].value_counts().to_dict())
