"""SEO2020 division (19) -> UN SDG goal (17). User-provided, not algorithmic -- the user
supplied a division-level SDG-alignment table directly and confirmed it as authoritative
("This is a good map"). Two things were resolved with the user before entering this table:

1. The user's pasted table's codes 10-26 matched our actual SEO2020 data exactly (same code,
   same label), but 27-32 didn't -- our real division 27 is "Transport" (the user's list had
   "Transport" at 31 instead) and 28 is "Expanding Knowledge" (ANZSRC's own basic/pure-research
   catch-all, no specific objective), while the user's list had "Society"/"Space"/"Sport,
   recreation and creative arts"/"Technology"/"Water" at 27-32 -- none of which exist
   anywhere in our SEO2020 or SEO2008 data. Confirmed with the user: match by label, not the
   pasted code; division 27 reuses the SDG from the user's own "Transport" row (SDG 11);
   division 28 -> SDG 9 (Industry, Innovation & Infrastructure), the user's direct
   instruction, since it has no counterpart in their list at all.
2. Two divisions (13, 18) originally listed two SDGs each. Per the user ("we don't need to
   use the alternates"), only the first-listed SDG is kept; the second is dropped entirely,
   not stored anywhere -- this mapping is single-valued throughout, no is_primary/alternates.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .hierarchy import write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

# seo2020_division_code -> sdg_code
_DIVISION_TO_SDG: dict[str, str] = {
    "10": "2",   # Animal production and animal primary products -> Zero Hunger
    "11": "8",   # Commercial services and tourism -> Decent Work and Economic Growth
    "12": "9",   # Construction -> Industry, Innovation and Infrastructure
    "13": "10",  # Culture and society -> Reduced Inequalities
    "14": "16",  # Defence -> Peace, Justice and Strong Institutions
    "15": "8",   # Economic framework -> Decent Work and Economic Growth
    "16": "4",   # Education and training -> Quality Education
    "17": "7",   # Energy -> Affordable and Clean Energy
    "18": "15",  # Environmental management -> Life on Land
    "19": "13",  # Environmental policy, climate change and natural hazards -> Climate Action
    "20": "3",   # Health -> Good Health and Well-being
    "21": "10",  # Indigenous -> Reduced Inequalities
    "22": "9",   # Information and communication services -> Industry, Innovation and Infrastructure
    "23": "16",  # Law, politics and community services -> Peace, Justice and Strong Institutions
    "24": "9",   # Manufacturing -> Industry, Innovation and Infrastructure
    "25": "12",  # Mineral resources (excl. energy resources) -> Responsible Consumption and Production
    "26": "2",   # Plant production and plant primary products -> Zero Hunger
    "27": "11",  # Transport -> Sustainable Cities and Communities
    "28": "9",   # Expanding Knowledge -> Industry, Innovation and Infrastructure (user override)
}


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "seo2020_division_to_sdg.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    seo_df = pd.read_csv(DATA_DIR / "seo_2020.csv", dtype=str, keep_default_na=False)
    division_label = dict(zip(seo_df[seo_df["level"] == "division"]["code"], seo_df[seo_df["level"] == "division"]["label"]))
    sdg_df = pd.read_csv(DATA_DIR / "sdg.csv", dtype=str, keep_default_na=False)
    goal_label = dict(zip(sdg_df[sdg_df["level"] == "goal"]["code"], sdg_df[sdg_df["level"] == "goal"]["label"]))

    assert set(_DIVISION_TO_SDG) == set(division_label), (
        f"mapping covers {sorted(_DIVISION_TO_SDG)}, but SEO2020 divisions are {sorted(division_label)}"
    )

    rows = [
        {
            "seo2020_division_code": div_code,
            "seo2020_division_label": division_label[div_code],
            "sdg_code": sdg_code,
            "sdg_label": goal_label[sdg_code],
            "confidence": 1.0,
            "notes": "",
        }
        for div_code, sdg_code in _DIVISION_TO_SDG.items()
    ]
    rows_by_code = {r["seo2020_division_code"]: r for r in rows}
    rows_by_code["27"]["notes"] = "division renumbered in source table (was 'Transport' at 31); matched by label"
    rows_by_code["28"]["notes"] = "no counterpart in source table; user-provided override"

    df = pd.DataFrame(rows)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(seed_path, index=False, encoding="utf-8")
    return df


def write_data_table(seed: pd.DataFrame) -> None:
    write_csv(seed, DATA_DIR / "seo2020_division_sdg.csv", ["seo2020_division_code"])
