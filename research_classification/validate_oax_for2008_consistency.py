"""Consistency checks for the OAX -> FOR2008 direction (curate_openalex_to_for2008.py). Both
are informational -- printed by build.py for spot-checking, never asserted on -- for the same
reason validate_oax_for2020_consistency.report_subfield_group_division_crossings() isn't: OAX
fields are broader than FOR2008 divisions, so a reviewed subfield pick legitimately landing
outside its field's division is common, not a bug.

Run: .venv/bin/python -m research_classification.validate_oax_for2008_consistency
"""

from __future__ import annotations

import pandas as pd

from .paths import BRIDGES_DIR, CANONICAL_DIR


def _primary(bridge: str) -> dict[str, str]:
    df = pd.read_csv(BRIDGES_DIR / f"{bridge}.csv", dtype=str, keep_default_na=False)
    df = df[df["is_primary"].isin(["True", "true"])]
    return dict(zip(df["source_code"], df["canonical_code"]))


def report_subfield_group_division_crossings() -> list[tuple[str, str, str]]:
    """(subfield, its field's FOR2008 division, its own group's FOR2008 division) wherever the
    two divisions differ -- e.g. OAX subfield "Law" (under field "Social Sciences" -> 16
    STUDIES IN HUMAN SOCIETY) correctly lands in group 1801 Law, division 18."""
    subfields = pd.read_csv(CANONICAL_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    division_of_field = _primary("bridge_openalex_for2008")
    group_of_subfield = _primary("bridge_openalex_for2008_group")
    crossings = []
    for subfield_code, field_code in zip(subfields["code"], subfields["parent_code"]):
        home = division_of_field[field_code]
        landed = group_of_subfield[subfield_code][:2]
        if home != landed:
            crossings.append((subfield_code, home, landed))
    return crossings


def report_round_trip_mismatches() -> list[tuple[str, str, str]]:
    """(subfield, FOR2020 division via OAX -> FOR2008 -> FOR2020, FOR2020 division via OAX ->
    FOR2020 directly) wherever they differ. The two paths are built independently (reviewed
    FOR2008 picks + ABS's official 2008 -> 2020 roll-up, vs the algorithmic OAX subfield ->
    FOR2020 group bridge), so a mismatch flags a row worth a second look on either side."""
    via_2008 = _primary("bridge_for2008_for2020")
    direct = _primary("bridge_openalex_for_group")
    mismatches = []
    for subfield_code, group_2008 in _primary("bridge_openalex_for2008_group").items():
        round_trip = via_2008.get(group_2008, "")[:2]
        direct_division = direct.get(subfield_code, "")[:2]
        if round_trip != direct_division:
            mismatches.append((subfield_code, round_trip, direct_division))
    return mismatches


def run() -> None:
    crossings = report_subfield_group_division_crossings()
    print(f"   {len(crossings)}/252 subfields land in a FOR2008 group outside their own field's "
          f"FOR2008 division (expected -- OAX fields are broader than FOR2008 divisions)")
    mismatches = report_round_trip_mismatches()
    print(f"   {len(mismatches)}/252 subfields' OAX -> FOR2008 -> FOR2020 round trip lands in a "
          f"different FOR2020 division than OAX -> FOR2020 directly: {mismatches}")


if __name__ == "__main__":
    run()
