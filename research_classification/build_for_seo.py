from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import io as rio

ROOT = Path(__file__).resolve().parent.parent
ABS_DIR = ROOT / "data_untracked" / "ABS_FOR_SEO"
DATA_DIR = ROOT / "data"

FOR_LEVELS = ["division", "group", "field"]
SEO_LEVELS = ["division", "group", "objective"]


def build_for() -> pd.DataFrame:
    df = rio.read_indented_hierarchy(
        ABS_DIR / "anzsrc2020_for.xlsx",
        sheet_name="Table 3",
        n_levels=3,
        level_names=FOR_LEVELS,
        header_row=10,
    )
    return df


def build_seo() -> pd.DataFrame:
    df = rio.read_indented_hierarchy(
        ABS_DIR / "anzsrc2020_seo.xlsx",
        sheet_name="Table 3",
        n_levels=3,
        level_names=SEO_LEVELS,
        header_row=10,
    )
    return df


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    for_df = build_for()
    seo_df = build_seo()
    from .hierarchy import write_csv

    write_csv(for_df, DATA_DIR / "for_2020.csv", ["code"])
    write_csv(seo_df, DATA_DIR / "seo_2020.csv", ["code"])
    return for_df, seo_df


if __name__ == "__main__":
    for_df, seo_df = run()
    print("FOR rows:", len(for_df), "SEO rows:", len(seo_df))
