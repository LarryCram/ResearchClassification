"""OpenAlex field (26) -> FOR division (23) [+ FOR group, when the best match happens to be
a group], algorithmic via cascade_match's exact-match-first cascade (see that module's
docstring for the full rationale). Previously a hand-typed table (Claude's own judgment, no
algorithm) -- rebuilt after finding it produced concrete wrong/incomplete answers this
session: OAX field 15 "Chemical Engineering" was only ever paired with a FOR2020 *division*,
never able to reach the exact-name group match `4004` "Chemical engineering" that turns out
to exist, because the hand-typed table's own structure never considered groups as an option.

Searches FOR2020 divisions AND groups together in one cascade call, not division-only --
found directly that several fields (Chemical Engineering, Veterinary, Nursing, Dentistry,
Materials Science) only resolve decisively once groups are in the candidate pool (each has
an exact-name match at group level; none does at division level alone). The division a
field's output uses is *derived* from wherever the winner sits (the group's own parent
division, if a group won) -- this seed's own external contract stays division-only (one row
per field, `for_division_code` always populated), since build_leiden.py and
curate_openalex_subfield_to_for_group.py both structurally depend on that, but the group
answer (when the winner was a group) is captured too, in `for_group_code`, so
curate_openalex_field_to_for_precise.py doesn't need to re-run the search from scratch.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import cascade_match as cm
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

# Escape hatch for fields the cascade can't resolve with confidence -- filled in only after
# inspecting the real run's output (never guessed in advance).
# field_code -> (for_division_code, for_group_code_or_empty, notes)
_MANUAL_OVERRIDES: dict[str, tuple[str, str, str]] = {
    # "Professions" vs "Sciences" are genuinely different words -- no amount of stemming or
    # spelling normalization closes this gap, unlike the Environmental Science/"science(s)"
    # case singularization fixed. Left to raw overlap, this landed on division 46
    # INFORMATION AND COMPUTING SCIENCES (36 shared words) over 42 HEALTH SCIENCES (31) and
    # 32 BIOMEDICAL AND CLINICAL SCIENCES (32) -- a noise-level three-way near-tie among
    # generic words ("clinical", "care", "assessment", "practice"...), not a real signal
    # either way. "Health Professions" (nursing, allied health, physiotherapy, etc.) is
    # obviously a health-sciences concept on inspection.
    "36": ("42", "", "obviously Health Sciences on inspection; lexical overlap was a noise-level near-tie with Info/Computing Sciences"),
}


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_field_to_for_division.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)

    field_label = dict(zip(fields["code"], fields["label"]))
    # Division 45 (Indigenous Studies) is excluded from the general candidate pool -- its
    # bag is far larger than every other division's (see cascade_match.py's module docstring)
    # and it already has its own dedicated resolution mechanism
    # (curate_for2020_division45_to_proxy.py).
    for_df = for_df[~for_df["code"].str.startswith("45")]
    div_label = dict(zip(for_df[for_df["level"] == "division"]["code"], for_df[for_df["level"] == "division"]["label"]))
    grp_label = dict(zip(for_df[for_df["level"] == "group"]["code"], for_df[for_df["level"] == "group"]["label"]))

    field_bags = cm.oax_field_bags(fields, subfields, topics)
    div_bags = cm.for_division_texts(for_df)
    grp_bags = cm.for_group_texts(for_df)
    candidates: list[cm.Candidate] = [(c, l, "division", div_bags.get(c, "")) for c, l in div_label.items()]
    candidates += [(c, l, "group", grp_bags.get(c, "")) for c, l in grp_label.items()]

    rows = []
    unresolved = []
    for field_code, field_name in field_label.items():
        # Manual overrides take priority over the algorithm even when it did produce a
        # (low-confidence, noise-level) answer -- that's the whole point of the escape hatch.
        if field_code in _MANUAL_OVERRIDES:
            div_code, grp_code, note = _MANUAL_OVERRIDES[field_code]
            rows.append(
                {
                    "openalex_field_id": field_code,
                    "openalex_field_name": field_name,
                    "for_division_code": div_code,
                    "for_division_label": div_label.get(div_code, ""),
                    "for_group_code": grp_code,
                    "for_group_label": grp_label.get(grp_code, "") if grp_code else "",
                    "is_primary": True,
                    "confidence": 0.7,
                    "match_method": "manual_override",
                    "notes": note,
                }
            )
            continue
        result = cm.cascade_resolve(field_name, field_bags.get(field_code, ""), candidates)
        if result is None:
            unresolved.append((field_code, field_name))
            continue
        code, label, level, confidence, match_method, note = result
        if level == "group":
            div_code = code[:2]
            grp_code, grp_lbl = code, label
        else:
            div_code, grp_code, grp_lbl = code, "", ""
        rows.append(
            {
                "openalex_field_id": field_code,
                "openalex_field_name": field_name,
                "for_division_code": div_code,
                "for_division_label": div_label.get(div_code, ""),
                "for_group_code": grp_code,
                "for_group_label": grp_lbl,
                "is_primary": True,
                "confidence": confidence,
                "match_method": match_method,
                "notes": note,
            }
        )

    if unresolved:
        print(f"  [openalex_field_to_for_division] {len(unresolved)} field(s) unresolved "
              f"(no exact match, below fuzzy floor): {unresolved}")

    df = pd.DataFrame(rows)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(seed_path, index=False, encoding="utf-8")
    return df


def to_bridge(seed: pd.DataFrame) -> pd.DataFrame:
    """Division-only, always -- this bridge's external contract is unchanged (see module
    docstring). The group answer, when present, lives in the seed CSV directly for
    curate_openalex_field_to_for_precise.py to read, not duplicated into this bridge."""
    rows = []
    for _, r in seed.iterrows():
        rows.append(
            {
                "source_system": "OpenAlex",
                "source_code": r["openalex_field_id"],
                "source_label": r["openalex_field_name"],
                "system": "FOR",
                "canonical_code": r["for_division_code"],
                "canonical_label": r["for_division_label"],
                "canonical_level": "division",
                "is_primary": str(r["is_primary"]) in ("True", "true", "1"),
                "match_method": r["match_method"],
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(seed.to_string())
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for.csv", ["source_code"])
    print("\nbridge rows:", len(bridge))
    print("\nmatch_method breakdown:")
    print(seed["match_method"].value_counts())
