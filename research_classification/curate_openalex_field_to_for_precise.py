"""OpenAlex field (26) -> FOR2020 group (213), a precision layer on top of
curate_openalex_for.py's division-level answer.

For each OAX field, curate_openalex_for.py already resolved a division (and, when the
winner happened to be an exact-name group match, a group too -- e.g. Chemical Engineering
-> group 4004). This script fills in the remaining fields: for each one whose division-level
answer did NOT come with a group, search only the groups *within that already-assigned
division* using cascade_match's raw bag-overlap scoring (same 2-step method, same
tokenizer -- see cascade_match.py's module docstring), and record a group only if one
clears the floor decisively. Fields with no confident group-level answer are simply absent
from this table -- resolver.py falls back to the division-level answer automatically for any
field not covered here, the same graceful-degradation pattern already used for OAX
subfield -> FOR2020 group coverage gaps.

Deliberately constrained to the field's own division (not an open 213-group search the way
curate_openalex_subfield_to_for_group.py's does) -- OAX fields are coarse, information-rich
nodes (each field's bag is every descendant topic's label), so their own division-level
search in curate_openalex_for.py is already a considered, high-signal answer; this layer's
job is only to sharpen it, not re-litigate it.

Requires a DECISIVE_MARGIN over the runner-up, not just MIN_OVERLAP -- checked directly: raw
overlap alone let "Immunology and Microbiology" land on group 3109 Zoology (7) over
3104 Evolutionary biology (6), a 1-word margin that's pure noise, while genuine wins (Medicine
-> Clinical sciences 29 vs runner-up 13; Social Sciences -> Sociology 30 vs 19) have real
separation. A handful of fields (Chemistry, Earth and Planetary Sciences, Economics, Energy,
Engineering, Environmental Science, Immunology and Microbiology, Materials Science) don't
clear this margin and are correctly left at division-level only -- forcing one narrow group to
represent a field this broad would be false precision, not a sharper answer.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import cascade_match as cm
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

MIN_OVERLAP = 5  # same floor as cascade_match.MIN_OVERLAP -- field bags are as rich as division bags
DECISIVE_MARGIN = 3  # top group must beat the runner-up by this much -- see module docstring

# Escape hatch for field/group pairs the cascade gets wrong -- filled in only after
# inspecting the real run's output.
# field_code -> (for_group_code, notes)
_MANUAL_OVERRIDES: dict[str, tuple[str, str]] = {}


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_field_to_for_group.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    division_seed = pd.read_csv(SEEDS_DIR / "openalex_field_to_for_division.csv", dtype=str, keep_default_na=False)
    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_df = for_df[~for_df["code"].str.startswith("45")]  # division 45 excluded; own proxy mechanism

    group_label = dict(zip(for_df[for_df["level"] == "group"]["code"], for_df[for_df["level"] == "group"]["label"]))
    groups_by_division: dict[str, list[str]] = {}
    for _, row in for_df[for_df["level"] == "group"].iterrows():
        groups_by_division.setdefault(row["parent_code"], []).append(row["code"])

    field_bags = cm.oax_field_bags(fields, subfields, topics)
    group_bags = cm.for_group_texts(for_df)

    rows = []
    for _, div_row in division_seed.iterrows():
        field_code, field_name = div_row["openalex_field_id"], div_row["openalex_field_name"]
        division = div_row["for_division_code"]

        if div_row["for_group_code"]:
            # Already precise -- curate_openalex_for.py's own exact match landed on a group.
            rows.append(
                {
                    "openalex_field_id": field_code,
                    "openalex_field_name": field_name,
                    "for_group_code": div_row["for_group_code"],
                    "for_group_label": div_row["for_group_label"],
                    "confidence": float(div_row["confidence"]),
                    "match_method": div_row["match_method"],
                    "notes": "from division-level exact match",
                }
            )
            continue

        if field_code in _MANUAL_OVERRIDES:
            group_code, note = _MANUAL_OVERRIDES[field_code]
            rows.append(
                {
                    "openalex_field_id": field_code,
                    "openalex_field_name": field_name,
                    "for_group_code": group_code,
                    "for_group_label": group_label.get(group_code, ""),
                    "confidence": 0.7,
                    "match_method": "manual_override",
                    "notes": note,
                }
            )
            continue

        candidate_groups = groups_by_division.get(division, [])
        if not candidate_groups:
            continue  # no group precision available -- division-level answer stands alone

        scored = sorted(
            ((g, cm.bag_overlap(field_bags.get(field_code, ""), group_bags.get(g, ""))) for g in candidate_groups),
            key=lambda t: (t[1], not cm.is_nec_code(t[0])),
            reverse=True,
        )
        top_group, top_overlap = scored[0]
        runner_up_overlap = scored[1][1] if len(scored) > 1 else 0
        if top_overlap < MIN_OVERLAP or top_overlap - runner_up_overlap < DECISIVE_MARGIN:
            continue  # nothing decisive within the division -- division-level answer stands alone

        source_tokens = cm.tokenize_words(field_bags.get(field_code, ""))
        confidence = round(min(1.0, top_overlap / len(source_tokens)), 3) if source_tokens else 0.0
        rows.append(
            {
                "openalex_field_id": field_code,
                "openalex_field_name": field_name,
                "for_group_code": top_group,
                "for_group_label": group_label.get(top_group, ""),
                "confidence": confidence,
                "match_method": "constrained_lexical",
                "notes": f"constrained to groups within division {division}",
            }
        )

    df = pd.DataFrame(rows)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(seed_path, index=False, encoding="utf-8")
    return df


def to_bridge(seed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in seed.iterrows():
        rows.append(
            {
                "source_system": "OpenAlex",
                "source_code": r["openalex_field_id"],
                "source_label": r["openalex_field_name"],
                "system": "FOR",
                "canonical_code": r["for_group_code"],
                "canonical_label": r["for_group_label"],
                "canonical_level": "group",
                "is_primary": True,
                "match_method": r["match_method"],
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(f"seed rows: {len(seed)} / 26 fields have group-level precision")
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for_field_group.csv", ["source_code"])
    print("\nmatch_method breakdown:")
    print(seed["match_method"].value_counts())
    print()
    print(seed.to_string())
