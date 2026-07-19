from __future__ import annotations

import difflib

import openpyxl
import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv
from .paths import BRIDGES_DIR, CANONICAL_DIR, RAW_DIR

ABS_DIR = RAW_DIR / "abs_for_seo"


def _lexical_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _canonical_label_lookup(system: str) -> dict[str, str]:
    fname = "for_2020.csv" if system == "FOR" else "seo_2020.csv"
    df = pd.read_csv(CANONICAL_DIR / fname, dtype=str, keep_default_na=False)
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


# FORD2015 (OECD) and NABS2007 (EU) international-scheme correspondences were dropped from
# this project entirely (not just excluded from resolution) -- like the hidden non-ASJC
# sheets in ASJC1.xlsx, they're not one of the named schemes this tool resolves from/to
# (OAX/FOR1998/FOR2008/FOR2020/SEO1998/SEO2008/SEO2020 in, OAX/FOR2020/SEO2020/FOR2020_AREA5 out),
# and NABS2007 in particular collided with 19 of SEO2020's own 19 divisions (95%) when it
# was still in scope, worse than the FOR1998/FOR2020 collision that prompted requiring an
# explicit from_scheme at all. If this coverage is needed again, the parsing logic for these
# indented, multi-row-per-subfield ABS correspondence tables is preserved in git history.


def run() -> dict[str, pd.DataFrame]:
    for2008 = resolve_primary(parse_2008_to_2020("FOR"), "FOR", "FOR2008")
    seo2008 = resolve_primary(parse_2008_to_2020("SEO"), "SEO", "SEO2008")
    write_csv(for2008, BRIDGES_DIR / "bridge_for2008_for2020.csv", ["source_code"])
    write_csv(seo2008, BRIDGES_DIR / "bridge_seo2008_seo2020.csv", ["source_code"])

    return {
        "bridge_for2008_for2020": for2008,
        "bridge_seo2008_seo2020": seo2008,
    }


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df), "primaries:", df["is_primary"].sum())
