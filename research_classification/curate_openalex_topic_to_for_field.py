"""OpenAlex topic (4,516) -> FOR2020 field (1,967 leaf codes), "clustering down" within each
subfield's already-matched group (curate_openalex_subfield_to_for_group.py): a topic's
candidate pool is restricted to the FOR2020 fields belonging to its own subfield's matched
group -- avg ~9.2 fields per group (min 1, max 32), never the full 1,967-field space. This is
only sound because that subfield->group bridge is itself now solid (zero below_floor
primaries across all 252 subfields, see that module's docstring and TODO.md) -- an untrusted
group pick here would propagate straight into a wrong candidate pool with no way to recover.

Topic text is label + keywords + summary, sourced from build_openalex.load_raw() (the raw
xlsx, joined on the numeric topic_id -- not on label text, which sidesteps the ~12 rows of
known mojibake entirely). FOR2020 field text is the label alone -- no field-level definitions
exist anywhere in the source data (io.read_definitions() only covers division/group), so this
side is deliberately thin; cascade_match.py's tokenizer already treats short/thin candidates
correctly (a field-centric overlap ratio here, not a topic-centric one, since the field label
is the thin/specific side and the topic bag is comparatively rich).

Matching order per topic, cheapest/most-decisive first:
1. Group has exactly one field -- no scoring needed, assign directly.
2. Exact word-set match (topic label vs. each candidate field's own label).
3. contains_match() -- one label's word set a unique proper subset of the other's.
4. Field-centric raw overlap ratio (overlap / candidate field's own token count, capped at
   1.0) -- last resort, below MIN_OVERLAP is recorded as `below_floor` (a real row is still
   always written, so resolve()'s coverage never has a gap to fall through) rather than a
   forced guess.

MIN_OVERLAP is lower here (1) than curate_openalex_subfield_to_for_group.py's (2): these
per-group candidate pools are far smaller (avg ~9 fields vs. 213 groups) and field labels are
short, so even a single shared, specific word is real signal at this granularity -- unlike a
single shared word among 213 candidates, which is far more likely to be noise.

Per the user's explicit instruction, there is no <20-case manual-review bar at this level
(unlike the subfield->group audit) -- genuinely uncertain topics are flagged via
`below_floor`/low confidence in the data (resolve() itself gracefully falls back to the
subfield's own group-level answer rather than surfacing a bad guess), not chased down
individually across ~4,500 rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import build_openalex
from . import cascade_match as cm
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

MIN_OVERLAP = 1
TOP_N_ALTERNATES = 5

# Escape hatch for topics the cascade gets wrong -- filled in only after inspecting a sample
# of the real run's output, the same pattern as every other curate_*.py in this pipeline. No
# mandatory full review at this granularity (see module docstring).
# topic_code -> (for_field_code, notes)
_MANUAL_OVERRIDES: dict[str, tuple[str, str]] = {
    "10200": ("320223", "Rheumatoid Arthritis Research and Therapies -- exact-fit 'Rheumatology and arthritis' field exists in the same matched group, missed because 'rheumatoid' and 'rheumatology' don't share a tokenized root"),
    "11171": ("310504", "Diabetes and associated disorders -- user override: epigenetic mechanisms in diabetes, staying within the topic's own matched Genetics group rather than crossing to a different group's Endocrinology field"),
}


def _topic_bag(row: pd.Series) -> str:
    return " ".join(str(x) for x in (row["topic_name"], row["keywords"], row["summary"]) if x)


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_topic_to_for_field.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    raw = build_openalex.load_raw()
    topic_bag = {r["topic_id"]: _topic_bag(r) for _, r in raw.iterrows()}

    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)

    subfield_group = pd.read_csv(DATA_DIR / "bridge_openalex_for_group.csv", dtype=str, keep_default_na=False)
    subfield_group = subfield_group[subfield_group["is_primary"].isin(["True", "true"])]
    group_of_subfield = dict(zip(subfield_group["source_code"], subfield_group["canonical_code"]))

    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    fields = for_df[for_df["level"] == "field"]
    field_label = dict(zip(fields["code"], fields["label"]))
    fields_by_group: dict[str, list[str]] = {}
    for code, parent in zip(fields["code"], fields["parent_code"]):
        fields_by_group.setdefault(parent, []).append(code)

    rows = []
    unresolved = []
    for _, t in topics.iterrows():
        topic_code, topic_label, subfield_code = t["code"], t["label"], t["parent_code"]
        bag = topic_bag.get(topic_code, topic_label)

        if topic_code in _MANUAL_OVERRIDES:
            field_code, note = _MANUAL_OVERRIDES[topic_code]
            rows.append(
                {
                    "openalex_topic_id": topic_code,
                    "openalex_topic_name": topic_label,
                    "for_field_code": field_code,
                    "for_field_label": field_label.get(field_code, ""),
                    "is_primary": True,
                    "confidence": 0.7,
                    "match_method": "manual_override",
                    "notes": note,
                }
            )
            continue

        group_code = group_of_subfield.get(subfield_code)
        candidates = fields_by_group.get(group_code, [])
        if not candidates:
            unresolved.append((topic_code, topic_label))
            continue

        if len(candidates) == 1:
            field_code = candidates[0]
            rows.append(
                {
                    "openalex_topic_id": topic_code,
                    "openalex_topic_name": topic_label,
                    "for_field_code": field_code,
                    "for_field_label": field_label.get(field_code, ""),
                    "is_primary": True,
                    "confidence": 1.0,
                    "match_method": "constrained_lexical",
                    "notes": "sole field in matched group",
                }
            )
            continue

        field_tokens = {f: cm.tokenize_words(field_label[f]) for f in candidates}
        overlaps = {f: len(cm.tokenize_words(bag) & field_tokens[f]) for f in candidates}

        topic_words = cm.exact_match_words(topic_label)
        exact_hits = {f for f in candidates if topic_words and cm.exact_match_words(field_label[f]) == topic_words}

        winner: str | None = None
        winner_method = ""
        winner_confidence = 0.0
        if len(exact_hits) == 1:
            winner = next(iter(exact_hits))
            winner_method, winner_confidence = "exact_match", 1.0
        elif topic_words:
            candidate_words = {f: cm.exact_match_words(field_label[f]) for f in candidates}
            contains_hit = cm.contains_match(topic_words, candidate_words)
            if contains_hit is not None:
                winner, winner_method, winner_confidence = contains_hit, "contains_match", 0.9

        ranked = sorted(candidates, key=lambda f: overlaps[f], reverse=True)
        if winner is not None:
            ranked = [winner] + [f for f in ranked if f != winner]
        else:
            top = ranked[0]
            if overlaps[top] >= MIN_OVERLAP:
                winner_method = "constrained_lexical"
                winner_confidence = round(min(1.0, overlaps[top] / len(field_tokens[top])), 3) if field_tokens[top] else 0.0
            else:
                winner_method = "below_floor"
                winner_confidence = 0.0

        for i, field_code in enumerate(ranked[: TOP_N_ALTERNATES + 1]):
            is_primary = i == 0
            if is_primary:
                confidence, method = winner_confidence, winner_method
            else:
                overlap = overlaps.get(field_code, 0)
                confidence = round(min(1.0, overlap / len(field_tokens[field_code])), 3) if field_tokens[field_code] else 0.0
                method = "constrained_lexical"
            rows.append(
                {
                    "openalex_topic_id": topic_code,
                    "openalex_topic_name": topic_label,
                    "for_field_code": field_code,
                    "for_field_label": field_label.get(field_code, ""),
                    "is_primary": is_primary,
                    "confidence": confidence,
                    "match_method": method,
                    "notes": "",
                }
            )

    if unresolved:
        print(f"  [openalex_topic_to_for_field] {len(unresolved)} topic(s) had no candidate "
              f"pool (subfield not matched to any group): {unresolved[:10]}{'...' if len(unresolved) > 10 else ''}")

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
                "source_code": r["openalex_topic_id"],
                "source_label": r["openalex_topic_name"],
                "system": "FOR",
                "canonical_code": r["for_field_code"],
                "canonical_label": r["for_field_label"],
                "canonical_level": "field",
                "is_primary": str(r["is_primary"]) in ("True", "true", "1"),
                "match_method": r["match_method"],
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(f"seed rows: {len(seed)}, unique topics covered: {seed['openalex_topic_id'].nunique()} / 4516")
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for_topic.csv", ["source_code"])
    print("bridge rows:", len(bridge))
    print("\nmatch_method breakdown (primary rows only):")
    primary = seed[seed["is_primary"].astype(str) == "True"]
    print(primary["match_method"].value_counts())
    print("\nconfidence distribution (primary rows only):")
    print(primary["confidence"].astype(float).describe())
