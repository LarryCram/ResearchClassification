"""Cross-level consistency checks for the OAX -> FOR2020 direction (curate_openalex_for.py,
curate_openalex_subfield_to_for_group.py, curate_openalex_topic_to_for_field.py). Two checks,
two different enforcement levels -- see each function's docstring for why.

Run: .venv/Scripts/python.exe -m research_classification.validate_oax_for2020_consistency
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"


def check_topic_field_nests_under_subfield_group() -> list[tuple[str, str, str, str]]:
    """Hard invariant: a topic's assigned FOR2020 field's parent group must equal that
    topic's own subfield's assigned FOR2020 group. This is structurally guaranteed by
    curate_openalex_topic_to_for_field.py's own design -- every topic's candidate pool is
    built from its subfield's matched group's own fields, so a mismatch can only mean a real
    bug (e.g. a manual override pointing outside the matched group). Returns the list of
    violations (empty if none) -- callers should treat any non-empty result as fatal.
    """
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    field_parent = dict(zip(for_df[for_df["level"] == "field"]["code"], for_df[for_df["level"] == "field"]["parent_code"]))

    sf_group = pd.read_csv(DATA_DIR / "bridge_openalex_for_group.csv", dtype=str, keep_default_na=False)
    sf_group = sf_group[sf_group["is_primary"].isin(["True", "true"])]
    group_of_subfield = dict(zip(sf_group["source_code"], sf_group["canonical_code"]))

    topic_field = pd.read_csv(DATA_DIR / "bridge_openalex_for_topic.csv", dtype=str, keep_default_na=False)
    topic_field = topic_field[topic_field["is_primary"].isin(["True", "true"])]
    field_of_topic = dict(zip(topic_field["source_code"], topic_field["canonical_code"]))

    subfield_of_topic = dict(zip(topics["code"], topics["parent_code"]))

    violations = []
    for topic_code, field_code in field_of_topic.items():
        subfield_code = subfield_of_topic.get(topic_code)
        expected_group = group_of_subfield.get(subfield_code)
        actual_group = field_parent.get(field_code)
        if expected_group != actual_group:
            violations.append((topic_code, field_code, expected_group or "", actual_group or ""))
    return violations


def report_subfield_group_division_crossings() -> list[tuple[str, str, str]]:
    """Informational only, NOT a hard invariant: a subfield's assigned FOR2020 group's parent
    division does not always equal the subfield's own parent OAX field's assigned FOR2020
    division -- curate_openalex_subfield_to_for_group.py documents this as a deliberate,
    common outcome (its own worked example: OAX subfield "Education" sits under field "Social
    Sciences" -> division 44, but correctly lands in FOR2020 division 39's "Curriculum and
    pedagogy" group). Returns the list of crossings for a human to spot-check, printed by
    build.py the same non-fatal way audit_encoding()'s findings are -- never asserted on.
    """
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)

    field_div = pd.read_csv(DATA_DIR / "bridge_openalex_for.csv", dtype=str, keep_default_na=False)
    field_div = field_div[field_div["is_primary"].isin(["True", "true"])]
    division_of_field = dict(zip(field_div["source_code"], field_div["canonical_code"]))

    sf_group = pd.read_csv(DATA_DIR / "bridge_openalex_for_group.csv", dtype=str, keep_default_na=False)
    sf_group = sf_group[sf_group["is_primary"].isin(["True", "true"])]
    group_of_subfield = dict(zip(sf_group["source_code"], sf_group["canonical_code"]))

    crossings = []
    for _, row in subfields.iterrows():
        subfield_code, field_code = row["code"], row["parent_code"]
        home_division = division_of_field.get(field_code)
        group_code = group_of_subfield.get(subfield_code)
        group_division = group_code[:2] if group_code else None
        if home_division and group_division and home_division != group_division:
            crossings.append((subfield_code, home_division, group_division))
    return crossings


def run() -> None:
    violations = check_topic_field_nests_under_subfield_group()
    if violations:
        raise AssertionError(
            f"{len(violations)} topic(s) resolve to a FOR2020 field outside their own "
            f"subfield's matched group: {violations[:10]}"
        )
    print(f"   topic->field nests correctly under subfield->group for all "
          f"{len(pd.read_csv(DATA_DIR / 'openalex_topics.csv'))} topics")

    crossings = report_subfield_group_division_crossings()
    print(f"   {len(crossings)}/252 subfields legitimately cross to a group in a different "
          f"division than their own field's division (expected, by design -- see docstring)")


if __name__ == "__main__":
    run()
