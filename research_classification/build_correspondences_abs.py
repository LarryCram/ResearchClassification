from __future__ import annotations

import difflib
from pathlib import Path

import openpyxl
import pandas as pd

from . import io as rio
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
ABS_DIR = ROOT / "data_untracked" / "ABS_FOR_SEO"
DATA_DIR = ROOT / "data"


def _lexical_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _canonical_label_lookup(system: str) -> dict[str, str]:
    fname = "for_2020.csv" if system == "FOR" else "seo_2020.csv"
    df = pd.read_csv(DATA_DIR / fname, dtype=str, keep_default_na=False)
    return dict(zip(df["code"], df["label"]))


def _level_for_code(code: str, system: str = "FOR") -> str:
    leaf = "field" if system == "FOR" else "objective"
    return {2: "division", 4: "group", 6: leaf}.get(len(code), leaf)


# ---------------------------------------------------------------------------
# 2008 <-> 2020 (official ABS correspondence, some rows flagged 'p' partial)
# ---------------------------------------------------------------------------


def parse_2008_to_2020(system: str) -> pd.DataFrame:
    sheet = "2008 FoR - 2020 FoR" if system == "FOR" else "2008 SEO - 2020 SEO"
    wb = openpyxl.load_workbook(
        ABS_DIR / "anzsrc2020_anzsrc2008_correspondences.xlsx", data_only=True
    )
    ws = wb[sheet]
    rows = []
    for row in ws.iter_rows(min_row=8, max_row=ws.max_row, max_col=6, values_only=True):
        code_2008, name_2008, code_2020, p_flag, name_2020 = row[0], row[1], row[2], row[3], row[4]
        if code_2008 is None or code_2020 is None:
            continue
        rows.append(
            {
                "source_code": str(code_2008).strip(),
                "source_label": str(name_2008).strip(),
                "canonical_code": str(int(code_2020)) if isinstance(code_2020, (int, float)) else str(code_2020).strip(),
                "canonical_label": str(name_2020).strip(),
                "is_partial": p_flag is not None,
            }
        )
    return pd.DataFrame(rows)


def resolve_primary(raw: pd.DataFrame, system: str, source_system: str) -> pd.DataFrame:
    canonical_lookup = _canonical_label_lookup(system)
    out_rows = []
    for source_code, grp in raw.groupby("source_code"):
        source_label = grp["source_label"].iloc[0]
        if len(grp) == 1:
            r = grp.iloc[0]
            confidence = 1.0 if not r["is_partial"] else _lexical_score(source_label, r["canonical_label"])
            out_rows.append(
                {
                    "source_system": source_system,
                    "source_code": source_code,
                    "source_label": source_label,
                    "system": system,
                    "canonical_code": r["canonical_code"],
                    "canonical_label": canonical_lookup.get(r["canonical_code"], r["canonical_label"]),
                    "canonical_level": _level_for_code(r["canonical_code"], system),
                    "is_primary": True,
                    "match_method": "explicit_official",
                    "confidence": round(confidence, 3),
                    "notes": "partial (p-flagged) single correspondence" if r["is_partial"] else "",
                }
            )
        else:
            scored = grp.copy()
            scored["score"] = scored["canonical_label"].apply(lambda lbl: _lexical_score(source_label, lbl))
            scored = scored.sort_values(["score", "canonical_code"], ascending=[False, True])
            for i, (_, r) in enumerate(scored.iterrows()):
                out_rows.append(
                    {
                        "source_system": source_system,
                        "source_code": source_code,
                        "source_label": source_label,
                        "system": system,
                        "canonical_code": r["canonical_code"],
                        "canonical_label": canonical_lookup.get(r["canonical_code"], r["canonical_label"]),
                        "canonical_level": _level_for_code(r["canonical_code"], system),
                        "is_primary": i == 0,
                        "match_method": "lexical",
                        "confidence": round(r["score"], 3),
                        "notes": f"lexical tiebreak among {len(grp)} p-flagged candidates",
                    }
                )
    return pd.DataFrame(out_rows, columns=BRIDGE_COLUMNS)


# ---------------------------------------------------------------------------
# FORD2015 -> FOR2020, NABS2007 -> SEO2020 (indented multi-row-per-subfield tables)
# ---------------------------------------------------------------------------


def parse_correspondence_indented(
    path: Path,
    sheet: str,
    header_row: int,
    source_label_prefix: str,
) -> pd.DataFrame:
    """Generic parser for the FORD2015/NABS2007-style tables: leftmost column(s) carry a
    forward-filled 'source subfield' label (combined code+label text), and every row below
    it contributes zero or more populated Division/Group/Included/Excluded columns (each
    also combined code+label text) as candidate correspondences at different granularity."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet]
    header = [c.value for c in next(ws.iter_rows(min_row=header_row, max_row=header_row))]

    div_col = next(i for i, h in enumerate(header) if h and "Divisions" in h)
    grp_col = next(i for i, h in enumerate(header) if h and "Groups" in h)
    inc_col = next(i for i, h in enumerate(header) if h and h.startswith("Included"))
    exc_col = next(i for i, h in enumerate(header) if h and h.startswith("Excluded"))
    subfield_col = 1  # second column is always the source subfield (2-digit level)

    rows = []
    current_subfield: tuple[str, str] | None = None
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row, values_only=True):
        sub_cell = row[subfield_col]
        parsed_sub = rio.split_code_label(sub_cell)
        if parsed_sub is not None:
            current_subfield = (parsed_sub[0], parsed_sub[1])
        if current_subfield is None:
            continue

        included = rio.split_code_label(row[inc_col]) if inc_col < len(row) else None
        excluded = rio.split_code_label(row[exc_col]) if exc_col < len(row) else None
        group = rio.split_code_label(row[grp_col]) if grp_col < len(row) else None
        division = rio.split_code_label(row[div_col]) if div_col < len(row) else None

        if included is None and group is None and division is None:
            continue
        rows.append(
            {
                "source_code": current_subfield[0],
                "source_label": f"{source_label_prefix}{current_subfield[1]}",
                "included_code": included[0] if included else "",
                "included_label": included[1] if included else "",
                "group_code": group[0] if group else "",
                "group_label": group[1] if group else "",
                "division_code": division[0] if division else "",
                "division_label": division[1] if division else "",
                "excluded_note": f"{excluded[0]} {excluded[1]}" if excluded else "",
            }
        )
    return pd.DataFrame(rows)


def _pick_existing_code(row: pd.Series, canonical_codes: set[str]) -> tuple[str, str, str] | None:
    """Walk included -> group -> division, returning the first (code, label, specificity)
    that actually exists in the current canonical table. The FORD2015 correspondence table
    was published against ANZSRC 2020's original June-2020 release; the FOR table in hand is
    a later (Oct-2025) revision, and at least one field-level code was renumbered/retired in
    between (450126 no longer exists) -- falling back to the row's own group/division code
    keeps that row usable instead of dropping it or crashing the build."""
    for level, code_col, label_col in [
        ("included", "included_code", "included_label"),
        ("group", "group_code", "group_label"),
        ("division", "division_code", "division_label"),
    ]:
        code = row[code_col]
        if code and code in canonical_codes:
            return code, row[label_col], level
    return None


def resolve_primary_indented(raw: pd.DataFrame, system: str, source_system: str) -> pd.DataFrame:
    canonical_lookup = _canonical_label_lookup(system)
    canonical_codes = set(canonical_lookup)
    resolved = raw.apply(lambda r: _pick_existing_code(r, canonical_codes), axis=1)
    stale = raw[resolved.isna()]
    if len(stale):
        stale_codes = sorted(
            (set(stale["included_code"]) | set(stale["group_code"]) | set(stale["division_code"])) - {""}
        )
        print(f"  [{source_system}] dropping {len(stale)} row(s) with no code found in the "
              f"current canonical table (likely stale vs. the correspondence file's vintage): {stale_codes}")
    raw = raw[resolved.notna()].copy()
    resolved = resolved[resolved.notna()]
    raw["canonical_code"] = [r[0] for r in resolved]
    raw["canonical_label"] = [r[1] for r in resolved]
    raw["specificity"] = [r[2] for r in resolved]

    _SPECIFICITY_RANK = {"included": 0, "group": 1, "division": 2}
    out_rows = []
    for source_code, grp in raw.groupby("source_code"):
        source_label = grp["source_label"].iloc[0]
        best_rank = grp["specificity"].map(_SPECIFICITY_RANK).min()
        candidates = grp[grp["specificity"].map(_SPECIFICITY_RANK) == best_rank].drop_duplicates(
            "canonical_code"
        )
        excluded_notes = "; ".join(sorted({n for n in grp["excluded_note"] if n}))
        if len(candidates) == 1:
            r = candidates.iloc[0]
            out_rows.append(
                {
                    "source_system": source_system,
                    "source_code": source_code,
                    "source_label": source_label,
                    "system": system,
                    "canonical_code": r["canonical_code"],
                    "canonical_label": canonical_lookup.get(r["canonical_code"], r["canonical_label"]),
                    "canonical_level": _level_for_code(r["canonical_code"], system),
                    "is_primary": True,
                    "match_method": "explicit_official",
                    "confidence": 1.0,
                    "notes": f"excluded: {excluded_notes}" if excluded_notes else "",
                }
            )
        else:
            scored = candidates.copy()
            scored["score"] = scored["canonical_label"].apply(lambda lbl: _lexical_score(source_label, lbl))
            scored = scored.sort_values(["score", "canonical_code"], ascending=[False, True])
            for i, (_, r) in enumerate(scored.iterrows()):
                out_rows.append(
                    {
                        "source_system": source_system,
                        "source_code": source_code,
                        "source_label": source_label,
                        "system": system,
                        "canonical_code": r["canonical_code"],
                        "canonical_label": canonical_lookup.get(r["canonical_code"], r["canonical_label"]),
                        "canonical_level": _level_for_code(r["canonical_code"], system),
                        "is_primary": i == 0,
                        "match_method": "lexical",
                        "confidence": round(r["score"], 3),
                        "notes": (
                            f"lexical tiebreak among {len(candidates)} same-specificity candidates"
                            + (f"; excluded: {excluded_notes}" if excluded_notes else "")
                        ),
                    }
                )
    return pd.DataFrame(out_rows, columns=BRIDGE_COLUMNS)


def run() -> dict[str, pd.DataFrame]:
    for2008 = resolve_primary(parse_2008_to_2020("FOR"), "FOR", "FOR2008")
    seo2008 = resolve_primary(parse_2008_to_2020("SEO"), "SEO", "SEO2008")
    write_csv(for2008, DATA_DIR / "bridge_for2008_for2020.csv", ["source_code"])
    write_csv(seo2008, DATA_DIR / "bridge_seo2008_seo2020.csv", ["source_code"])

    ford_raw = parse_correspondence_indented(
        ABS_DIR / "anzsrc2020for_ford_correspondence.xlsx", "Table 1", 8, "FORD2015 subfield "
    )
    ford_bridge = resolve_primary_indented(ford_raw, "FOR", "FORD2015")
    write_csv(ford_bridge, DATA_DIR / "bridge_ford2015_for2020.csv", ["source_code"])

    nabs_raw = parse_correspondence_indented(
        ABS_DIR / "anzsrc2020seo_nabs_correspondence.xlsx", "Table 1", 8, "NABS2007 chapter "
    )
    for col in ["included_label", "group_label", "division_label"]:
        nabs_raw[col] = nabs_raw[col].replace({"Antartic": "Antarctic"}, regex=True)
    nabs_bridge = resolve_primary_indented(nabs_raw, "SEO", "NABS2007")
    write_csv(nabs_bridge, DATA_DIR / "bridge_nabs2007_seo2020.csv", ["source_code"])

    return {
        "bridge_for2008_for2020": for2008,
        "bridge_seo2008_seo2020": seo2008,
        "bridge_ford2015_for2020": ford_bridge,
        "bridge_nabs2007_seo2020": nabs_bridge,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df), "primaries:", df["is_primary"].sum())
