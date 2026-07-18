"""Diagnostic dump tool for reviewing OAX -> FOR2020 bridge quality by direct (agent/human)
judgment, not another round of formula-tuning -- see TODO.md for why this project prefers
inspection + `_MANUAL_OVERRIDES` escape hatches over chasing a cleverer score.

Not wired into build.py -- this is a review aid, run standalone, re-run after edits to
`_MANUAL_OVERRIDES` in curate_openalex_subfield_to_for_group.py (or curate_openalex_for.py) to
self-check the result. Kept committed so the audit methodology (and how to re-run it, e.g.
after a future OpenAlex/FOR2020 revision) stays documented and reproducible.

Run: .venv/Scripts/python.exe -m research_classification.audit_oax_for_bridges [subfield|field]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"

TOP_N_ALTERNATES_SHOWN = 5


def _load_for_hierarchy() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)


def dump_field_to_division() -> None:
    """The 26-row OAX field -> FOR2020 division bridge, one block per field."""
    bridge = pd.read_csv(DATA_DIR / "bridge_openalex_for.csv", dtype=str, keep_default_na=False)
    for_df = _load_for_hierarchy()
    div_label = dict(zip(for_df[for_df["level"] == "division"]["code"], for_df[for_df["level"] == "division"]["label"]))

    for source_code, grp in bridge.groupby("source_code", sort=False):
        grp = grp.sort_values("is_primary", ascending=False)
        primary = grp.iloc[0]
        print(f"\n=== OAX field {source_code}: {primary['source_label']} ===")
        print(f"  pick: FOR {primary['canonical_code']} {primary['canonical_label']} "
              f"({primary['match_method']}, conf={primary['confidence']})")
        if primary["notes"]:
            print(f"  notes: {primary['notes']}")
        print("  all 23 divisions:", ", ".join(f"{c} {l}" for c, l in div_label.items()))


def dump_subfield_to_group() -> None:
    """The 252-row OAX subfield -> FOR2020 group bridge, batched by parent OAX field so the
    review is tractable in ~26 chunks of ~9-10 subfields rather than one 252-row wall."""
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    field_label = dict(zip(fields["code"], fields["label"]))
    subfield_field = dict(zip(subfields["code"], subfields["parent_code"]))

    field_div_bridge = pd.read_csv(DATA_DIR / "bridge_openalex_for.csv", dtype=str, keep_default_na=False)
    field_div_bridge = field_div_bridge[field_div_bridge["is_primary"].isin(["True", "true"])]
    division_of_field = dict(zip(field_div_bridge["source_code"], field_div_bridge["canonical_code"]))
    division_label_of_field = dict(zip(field_div_bridge["source_code"], field_div_bridge["canonical_label"]))

    for_df = _load_for_hierarchy()
    group_rows = for_df[for_df["level"] == "group"]
    groups_by_division: dict[str, list[tuple[str, str]]] = {}
    for _, row in group_rows.iterrows():
        groups_by_division.setdefault(row["parent_code"], []).append((row["code"], row["label"]))
    div_label = dict(zip(for_df[for_df["level"] == "division"]["code"], for_df[for_df["level"] == "division"]["label"]))

    bridge = pd.read_csv(DATA_DIR / "bridge_openalex_for_group.csv", dtype=str, keep_default_na=False)
    bridge["confidence"] = bridge["confidence"].astype(float)

    n_below_floor = 0
    for field_code in sorted(fields["code"], key=int):
        subs = subfields[subfields["parent_code"] == field_code]
        if subs.empty:
            continue
        home_div = division_of_field.get(field_code, "?")
        print(f"\n########## OAX field {field_code} {field_label.get(field_code, '')} "
              f"-> home division {home_div} {division_label_of_field.get(field_code, '')} ##########")

        for _, sub in subs.iterrows():
            subfield_code, subfield_name = sub["code"], sub["label"]
            grp = bridge[bridge["source_code"] == subfield_code].sort_values(
                "is_primary", ascending=False
            )
            if grp.empty:
                continue
            primary = grp.iloc[0]
            alternates = grp.iloc[1 : 1 + TOP_N_ALTERNATES_SHOWN]
            flag = " <-- BELOW_FLOOR" if primary["match_method"] == "below_floor" else ""
            if primary["match_method"] == "below_floor":
                n_below_floor += 1
            print(f"\n  --- subfield {subfield_code}: {subfield_name} ---{flag}")
            print(f"    pick: FOR group {primary['canonical_code']} {primary['canonical_label']} "
                  f"({primary['match_method']}, conf={primary['confidence']})")
            if not alternates.empty:
                alt_str = "; ".join(
                    f"{r['canonical_code']} {r['canonical_label']} (conf={r['confidence']})"
                    for _, r in alternates.iterrows()
                )
                print(f"    alternates: {alt_str}")

            pick_div = primary["canonical_code"][:2] if primary["canonical_code"] else ""
            home_groups = groups_by_division.get(home_div, [])
            print(f"    home division {home_div} {div_label.get(home_div, '')} groups: "
                  + ", ".join(f"{c} {l}" for c, l in home_groups))
            if pick_div and pick_div != home_div:
                pick_groups = groups_by_division.get(pick_div, [])
                print(f"    pick's division {pick_div} {div_label.get(pick_div, '')} groups: "
                      + ", ".join(f"{c} {l}" for c, l in pick_groups))

    print(f"\n\n=== TOTAL below_floor primaries: {n_below_floor} ===")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "subfield"
    if target == "field":
        dump_field_to_division()
    else:
        dump_subfield_to_group()
