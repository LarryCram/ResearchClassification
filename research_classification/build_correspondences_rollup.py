"""Derives FOR1998/FOR2008 -> FOR2020 and SEO1998/SEO2008 -> SEO2020 division (2-digit) and
group (4-digit) bridge rows by rolling up the already-built leaf-level (6-digit field/
objective) bridge tables via majority vote -- the same pattern as
curate_for2020_to_openalex.py's division-level subfield roll-up. None of these four vintage
correspondences' official ABS source publishes anything coarser than leaf level (confirmed
directly against the source sheets -- see TODO.md), so this is the only way to reach
division/group precision at all.

Source-side division/group titles come from data_untracked/12970_1998_2008.xlsx, the only
source file in this checkout that lists these vintages' own division/group names (the usual
ABS_FOR_SEO correspondence sources this pipeline otherwise reads don't carry them). FOR2008's
and SEO2008's own codes are natively 2/4/6-digit (division/group/leaf each genuinely
distinct-width); a leaf code's own [:2]/[:4] prefix already equals its parent division/group
code. FOR1998 and SEO1998 both encode every level in a flat 6-digit space instead (e.g. FOR1998
division ends "0000", discipline/group ends "00"; SEO1998 subdivision ends "0000", group ends
"00"), but a leaf code's [:2]/[:4] prefix equals that same padded parent code with the padding
stripped -- so plain string slicing on the already-built leaf-level bridge is enough for all
four vintages, no need to re-derive parentage from the source workbook.

SEO1998 and SEO2008 each have an extra, coarser tier with no SEO2020 equivalent at all --
SEO1998's own "Division" (5 codes) and SEO2008's own "Sector" (5 codes) -- skipped entirely;
the tier that actually corresponds to SEO2020's own division is SEO1998's "Subdivision" and
SEO2008's own "Division" (see examples/map_category_seo.py's docstring for the code-count
reasoning behind that match).
"""

from __future__ import annotations

from collections import Counter

import openpyxl
import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv
from .paths import BRIDGES_DIR, CANONICAL_DIR, RAW_DIR

LABELS_XLSX = RAW_DIR / "abs_for_seo" / "12970_1998_2008.xlsx"


def _source_titles(sheet: str, level: str) -> dict[str, str]:
    """code (at that level's own native width in the source sheet) -> title. Recombines a
    title that this workbook itself split across columns C/D at an embedded comma (affects
    a handful of 1998_FOR titles, e.g. "LAW, POLITICS AND COMMUNITY SERVICES")."""
    wb = openpyxl.load_workbook(LABELS_XLSX, data_only=True)
    ws = wb[sheet]
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        code, lvl, title = str(row[0]), row[1], row[2]
        if lvl != level:
            continue
        if len(row) > 3 and row[3] is not None:
            title = f"{title}, {row[3]}"
        out[code] = title
    return out


def _for1998_division_labels() -> dict[str, str]:
    return {code[:2]: title for code, title in _source_titles("1998_FOR", "Division").items()}


def _for1998_group_labels() -> dict[str, str]:
    return {code[:4]: title for code, title in _source_titles("1998_FOR", "Discipline").items()}


def _for2008_division_labels() -> dict[str, str]:
    return {code.zfill(2): title for code, title in _source_titles("2008_FOR", "Division").items()}


def _for2008_group_labels() -> dict[str, str]:
    return {code.zfill(4): title for code, title in _source_titles("2008_FOR", "Group").items()}


def _seo1998_division_labels() -> dict[str, str]:
    return {code[:2]: title for code, title in _source_titles("1998_SEO", "Subdivision").items()}


def _seo1998_group_labels() -> dict[str, str]:
    return {code[:4]: title for code, title in _source_titles("1998_SEO", "Group").items()}


def _seo2008_division_labels() -> dict[str, str]:
    return {code.zfill(2): title for code, title in _source_titles("2008_SEO", "Division").items()}


def _seo2008_group_labels() -> dict[str, str]:
    return {code.zfill(4): title for code, title in _source_titles("2008_SEO", "Group").items()}


def _rollup(
    field_bridge: pd.DataFrame,
    width: int,
    source_system: str,
    source_labels: dict[str, str],
    canonical_lookup: dict[str, str],
    canonical_level: str,
) -> pd.DataFrame:
    """Majority vote: for each source-side division/group prefix, the FOR2020 canonical
    division/group that the largest share of its own leaf-level fields resolve to (via the
    existing field-level bridge) becomes primary; confidence is that share. Ties keep the
    lowest canonical code first (Counter.most_common()'s own stable order over insertion)."""
    primaries = field_bridge[field_bridge["is_primary"]].copy()
    primaries["source_prefix"] = primaries["source_code"].str.slice(0, width)
    primaries["canonical_prefix"] = primaries["canonical_code"].str.slice(0, width)

    rows = []
    for prefix, grp in primaries.groupby("source_prefix"):
        if prefix not in source_labels:
            continue  # a leaf field whose parent title we don't have -- skip, don't guess
        counts = Counter(grp["canonical_prefix"])
        total = len(grp)
        for i, (canonical_prefix, n) in enumerate(counts.most_common()):
            rows.append({
                "source_system": source_system,
                "source_code": prefix,
                "source_label": source_labels[prefix],
                "system": source_system[:3],  # "FOR1998"/"FOR2008" -> "FOR", "SEO1998"/"SEO2008" -> "SEO"
                "canonical_code": canonical_prefix,
                "canonical_label": canonical_lookup.get(canonical_prefix, ""),
                "canonical_level": canonical_level,
                "is_primary": i == 0,
                "match_method": "derived_empirical",
                "confidence": round(n / total, 3),
                "notes": f"rolled up from {total} {source_system} leaf-level mapping(s), {n} agreeing",
            })
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


# Hand-coded facts for FOR2008 fields that have no FOR2020 field-level (or even group-level
# exact-name) equivalent at all -- confirmed absent from the official ABS correspondence and
# from label-matching alike. Resolved by direct user judgment to the best-fit FOR2020 GROUP
# instead (a deliberate level-coarsening, same pattern as OAX/Leiden falling back to
# division-level when no group-level match exists): 119901 "Podiatry" and 119903 "Therapies
# and Therapeutic Technology" both land under FOR2020 group 4201 "Allied health and
# rehabilitation science" (no FOR2020 field named after either); 119902 "Medical
# Biotechnology" matches FOR2020 group 3206 "Medical biotechnology" by name exactly, but
# only at group level (FOR2020 splits that group into more specific fields with no NEC field
# generic enough to be "Medical Biotechnology" itself).
# FOR1998 360205 "Social Policy" and 360206 "Defence Policy" (both under discipline 3602
# "Policy and Administration", which itself already resolves cleanly to FOR2020 group 4407)
# have no FOR2020 field of their own -- FOR2020's own 4407 has no "social"/"defence"-specific
# child field, just its own NEC field. Resolved by direct user judgment to their parent
# discipline's own FOR2020 group target, 4407 "Policy and administration".
# SEO1998 770299 "Atmosphere not elsewhere classified" has no exact-name SEO2020 objective,
# but SEO2020's own 180199 "Air quality, atmosphere and weather not elsewhere classified" is
# the same NEC catch-all concept one level up, under the matching topic area (objective, not
# a coarsened group -- both are already leaf-level).
MANUAL_FIELD_OVERRIDES: dict[str, list[tuple[str, str, str, str]]] = {
    "FOR1998": [
        ("360205", "Social Policy", "4407", "Policy and administration"),
        ("360206", "Defence Policy", "4407", "Policy and administration"),
    ],
    "FOR2008": [
        ("119901", "Podiatry", "4201", "Allied health and rehabilitation science"),
        ("119902", "Medical Biotechnology", "3206", "Medical biotechnology"),
        ("119903", "Therapies and Therapeutic Technology", "4201", "Allied health and rehabilitation science"),
    ],
    "SEO1998": [
        ("770299", "Atmosphere not elsewhere classified", "180199",
         "Air quality, atmosphere and weather not elsewhere classified"),
    ],
}


def _manual_override_rows(source_system: str) -> pd.DataFrame:
    system = source_system[:3]  # "FOR1998"/"FOR2008" -> "FOR", "SEO1998"/"SEO2008" -> "SEO"
    leaf_level = "field" if system == "FOR" else "objective"
    rows = [
        {
            "source_system": source_system,
            "source_code": source_code,
            "source_label": source_label,
            "system": system,
            "canonical_code": canonical_code,
            "canonical_label": canonical_label,
            "canonical_level": "group" if len(canonical_code) == 4 else leaf_level,
            "is_primary": True,
            "match_method": "user_provided",
            "confidence": 1.0,
            "notes": f"hand-coded: no {system}2020 {leaf_level}/group match found officially or by label, "
                     "resolved by direct user judgment",
        }
        for source_code, source_label, canonical_code, canonical_label in MANUAL_FIELD_OVERRIDES.get(source_system, [])
    ]
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


def _load_leaf_bridge(filename: str, leaf_level: str) -> pd.DataFrame:
    df = pd.read_csv(BRIDGES_DIR / filename, dtype=str, keep_default_na=False)
    df["is_primary"] = df["is_primary"].isin(["True", "true"])
    # Filter to leaf-level rows only -- makes this idempotent to re-run even after a prior
    # run already wrote division/group rollup rows into this same file.
    return df[df["canonical_level"] == leaf_level]


def run() -> dict[str, pd.DataFrame]:
    for2020 = pd.read_csv(CANONICAL_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_canonical_lookup = dict(zip(for2020["code"], for2020["label"]))
    seo2020 = pd.read_csv(CANONICAL_DIR / "seo_2020.csv", dtype=str, keep_default_na=False)
    seo_canonical_lookup = dict(zip(seo2020["code"], seo2020["label"]))

    for1998_field = _load_leaf_bridge("bridge_for1998_for2020.csv", "field")
    for2008_field = _load_leaf_bridge("bridge_for2008_for2020.csv", "field")
    seo1998_field = _load_leaf_bridge("bridge_seo1998_seo2020.csv", "objective")
    seo2008_field = _load_leaf_bridge("bridge_seo2008_seo2020.csv", "objective")

    for1998_field = pd.concat([for1998_field, _manual_override_rows("FOR1998")], ignore_index=True)
    for2008_field = pd.concat([for2008_field, _manual_override_rows("FOR2008")], ignore_index=True)
    seo1998_field = pd.concat([seo1998_field, _manual_override_rows("SEO1998")], ignore_index=True)
    seo2008_field = pd.concat([seo2008_field, _manual_override_rows("SEO2008")], ignore_index=True)

    for1998_div = _rollup(for1998_field, 2, "FOR1998", _for1998_division_labels(), for_canonical_lookup, "division")
    for1998_group = _rollup(for1998_field, 4, "FOR1998", _for1998_group_labels(), for_canonical_lookup, "group")
    for2008_div = _rollup(for2008_field, 2, "FOR2008", _for2008_division_labels(), for_canonical_lookup, "division")
    for2008_group = _rollup(for2008_field, 4, "FOR2008", _for2008_group_labels(), for_canonical_lookup, "group")
    seo1998_div = _rollup(seo1998_field, 2, "SEO1998", _seo1998_division_labels(), seo_canonical_lookup, "division")
    seo1998_group = _rollup(seo1998_field, 4, "SEO1998", _seo1998_group_labels(), seo_canonical_lookup, "group")
    seo2008_div = _rollup(seo2008_field, 2, "SEO2008", _seo2008_division_labels(), seo_canonical_lookup, "division")
    seo2008_group = _rollup(seo2008_field, 4, "SEO2008", _seo2008_group_labels(), seo_canonical_lookup, "group")

    for1998_full = pd.concat([for1998_field, for1998_div, for1998_group], ignore_index=True)
    for2008_full = pd.concat([for2008_field, for2008_div, for2008_group], ignore_index=True)
    seo1998_full = pd.concat([seo1998_field, seo1998_div, seo1998_group], ignore_index=True)
    seo2008_full = pd.concat([seo2008_field, seo2008_div, seo2008_group], ignore_index=True)

    write_csv(for1998_full, BRIDGES_DIR / "bridge_for1998_for2020.csv", ["source_code"])
    write_csv(for2008_full, BRIDGES_DIR / "bridge_for2008_for2020.csv", ["source_code"])
    write_csv(seo1998_full, BRIDGES_DIR / "bridge_seo1998_seo2020.csv", ["source_code"])
    write_csv(seo2008_full, BRIDGES_DIR / "bridge_seo2008_seo2020.csv", ["source_code"])

    return {
        "bridge_for1998_for2020": for1998_full,
        "bridge_for2008_for2020": for2008_full,
        "bridge_seo1998_seo2020": seo1998_full,
        "bridge_seo2008_seo2020": seo2008_full,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df), "rows total; by level:", df["canonical_level"].value_counts().to_dict())
