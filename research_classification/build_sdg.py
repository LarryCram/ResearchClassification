"""Canonical UN Sustainable Development Goals table: 5 pillars ("the 5 Ps" -- People,
Planet, Prosperity, Peace, Partnership) plus the 17 goals nested under them. Both are fixed,
stable UN content -- hardcoded here, no source file to parse.
"""

from __future__ import annotations

import pandas as pd

from .hierarchy import write_csv
from .paths import CANONICAL_DIR

# code -> (label, parent pillar code)
_GOALS: dict[str, tuple[str, str]] = {
    "1": ("No Poverty", "PEOPLE"),
    "2": ("Zero Hunger", "PEOPLE"),
    "3": ("Good Health and Well-being", "PEOPLE"),
    "4": ("Quality Education", "PEOPLE"),
    "5": ("Gender Equality", "PEOPLE"),
    "6": ("Clean Water and Sanitation", "PLANET"),
    "7": ("Affordable and Clean Energy", "PROSPERITY"),
    "8": ("Decent Work and Economic Growth", "PROSPERITY"),
    "9": ("Industry, Innovation and Infrastructure", "PROSPERITY"),
    "10": ("Reduced Inequalities", "PROSPERITY"),
    "11": ("Sustainable Cities and Communities", "PROSPERITY"),
    "12": ("Responsible Consumption and Production", "PLANET"),
    "13": ("Climate Action", "PLANET"),
    "14": ("Life Below Water", "PLANET"),
    "15": ("Life on Land", "PLANET"),
    "16": ("Peace, Justice and Strong Institutions", "PEACE"),
    "17": ("Partnerships for the Goals", "PARTNERSHIP"),
}

_PILLARS: dict[str, str] = {
    "PEOPLE": "People",
    "PLANET": "Planet",
    "PROSPERITY": "Prosperity",
    "PEACE": "Peace",
    "PARTNERSHIP": "Partnership",
}


def run() -> pd.DataFrame:
    rows = [{"code": code, "level": "pillar", "label": label, "parent_code": ""} for code, label in _PILLARS.items()]
    rows += [
        {"code": code, "level": "goal", "label": label, "parent_code": parent}
        for code, (label, parent) in _GOALS.items()
    ]
    df = pd.DataFrame(rows)
    write_csv(df, CANONICAL_DIR / "sdg.csv", ["level", "code"])
    return df
