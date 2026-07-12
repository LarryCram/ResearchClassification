"""Demo: for every SEO1998 and SEO2008 code in data_untracked/12970_1998_2008.xlsx, at
division (2-digit), group (4-digit), and objective (6-digit) level, try
resolver.resolve(code, from_scheme, "SEO2020") and report the match/failure count at each
of the 6 (scheme x level) combinations. Mirrors map_category_for.py's approach for FOR.

Both legacy SEO vintages have an extra, coarser tier with no SEO2020 equivalent at all --
SEO1998's own "Division" (5 codes, 1 digit) and SEO2008's own "Sector" (5 codes, a letter
A-E) -- and neither is tested here, since SEO2020 itself only has division/group/objective
(19/128/840), same 3 levels as FOR2020. The tier that actually corresponds to SEO2020's
"division" is SEO1998's "Subdivision" (18 codes) and SEO2008's own "Division" (16 codes) --
matched by which level's code count is close to SEO2020's, not by matching level names.

SEO2008's own codes are natively 2/4/6 digits, same shape as SEO2020's. SEO1998's are not --
like FOR1998, it encodes every level in a flat 6-digit space, zero-padded on the right
(subdivision "610000", group "610100", class "610101"). To test 1998 division/group
like-for-like with 2008, this script strips that padding: subdivision drops the trailing
"0000", group drops the trailing "00".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import openpyxl

from research_classification import Resolver
from research_classification.resolver import FromScheme

XLSX = ROOT / "data_untracked" / "12970_1998_2008.xlsx"


def _read_sheet(sheet: str) -> list[tuple[str, str, str]]:
    """Returns (code, level, title) rows, recombining the title with a comma when a
    trailing 4th column is populated (a handful of titles containing a comma were split
    across columns C/D in this workbook)."""
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb[sheet]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        code, level, title = row[0], row[1], row[2]
        if len(row) > 3 and row[3] is not None:
            title = f"{title}, {row[3]}"
        rows.append((str(code), level, title))
    return rows


def seo1998_codes(level: str) -> list[tuple[str, str]]:
    sheet_level = {"div": "Subdivision", "group": "Group", "objective": "Class"}[level]
    rows = [(code, title) for code, lvl, title in _read_sheet("1998_SEO") if lvl == sheet_level]
    if level == "div":
        return [(code[:2], title) for code, title in rows]
    if level == "group":
        return [(code[:4], title) for code, title in rows]
    return rows  # objective: already the native 6-digit code, no stripping needed


def seo2008_codes(level: str) -> list[tuple[str, str]]:
    sheet_level = {"div": "Division", "group": "Group", "objective": "Objective"}[level]
    width = {"div": 2, "group": 4, "objective": 6}[level]
    return [(code.zfill(width), title) for code, lvl, title in _read_sheet("2008_SEO") if lvl == sheet_level]


def run(resolver: Resolver, label: str, from_scheme: FromScheme, codes: list[tuple[str, str]]) -> None:
    failed = []
    matches = []
    for code, title in codes:
        try:
            result = resolver.resolve(code, from_scheme, "SEO2020")
        except LookupError:
            failed.append((code, title))
            continue
        if result is None:  # a known, documented absence (resolve() already warned) -- see TODO.md
            failed.append((code, title))
            continue
        matches.append((code, title, result.code, result.label))
    matched = len(codes) - len(failed)
    print(f"{label}: {matched}/{len(codes)} matched, {len(failed)} failed")
    if matches:
        for code, title, target_code, target_label in matches[:4]:
            print(f"    {code} ({title})  ->  {target_code} ({target_label})")
    if failed:
        sample = ", ".join(f"{c} ({t})" for c, t in failed[:5])
        more = " ..." if len(failed) > 5 else ""
        print(f"    first failures: {sample}{more}")


def main() -> None:
    resolver = Resolver()
    for level, digits in [("div", 2), ("group", 4), ("objective", 6)]:
        run(resolver, f"SEO1998 {digits}-digit -> SEO2020", "SEO1998", seo1998_codes(level))
    for level, digits in [("div", 2), ("group", 4), ("objective", 6)]:
        run(resolver, f"SEO2008 {digits}-digit -> SEO2020", "SEO2008", seo2008_codes(level))


if __name__ == "__main__":
    main()
