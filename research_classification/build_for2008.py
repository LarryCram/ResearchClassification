"""Canonical FOR2008 table (22 divisions, 157 groups, 1,241 fields), from the "2008_FOR" sheet
of 12970_1998_2008.xlsx -- the only source in raw/ that lists FOR2008's own division and group
titles (the ABS 2008<->2020 and 1998<->2008 correspondence workbooks carry leaf-level codes
only). The sheet stores codes as integers, so leading zeros are lost ("1" for division 01,
"101" for group 0101); each level's native width is restored here.

Exists so FOR2008 can be a resolve() *target* (OAX -> FOR2008, see
curate_openalex_to_for2008.py) with real labels and validated codes -- as a from_scheme,
FOR2008 is still served by bridge_for2008_for2020.csv's own source_code/source_label columns.
"""

from __future__ import annotations

import openpyxl
import pandas as pd

from .hierarchy import write_csv
from .paths import CANONICAL_DIR, RAW_DIR

SOURCE_XLSX = RAW_DIR / "abs_for_seo" / "12970_1998_2008.xlsx"

_WIDTH = {"Division": 2, "Group": 4, "Field": 6}


def build() -> pd.DataFrame:
    wb = openpyxl.load_workbook(SOURCE_XLSX, data_only=True)
    ws = wb["2008_FOR"]
    rows = []
    for code, level, title in ws.iter_rows(min_row=2, max_col=3, values_only=True):
        if level not in _WIDTH:
            continue
        code = str(code).strip().zfill(_WIDTH[level])
        rows.append({
            "code": code,
            "level": level.lower(),
            "label": str(title).strip(),
            "parent_code": "" if level == "Division" else code[: _WIDTH[level] - 2],
        })
    return pd.DataFrame(rows)


def run() -> pd.DataFrame:
    df = build()
    write_csv(df, CANONICAL_DIR / "for_2008.csv", ["code"])
    return df


if __name__ == "__main__":
    df = run()
    print(df["level"].value_counts().to_dict())
