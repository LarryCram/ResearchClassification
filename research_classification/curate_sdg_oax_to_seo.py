"""Derives (SDG goal, OAX subfield) -> SEO2020 division associations, to disambiguate the
cases where a plain SDG goal alone maps to more than one SEO2020 division (or, for 5 goals,
no division at all) in the user-curated seo2020_division_sdg.csv. 17 SDG goals sit over 19
SEO2020 divisions, so several goals collide (e.g. goal 9 "Industry, Innovation and
Infrastructure" has 4: divisions 12/22/24/28); knowing which OAX subfield a real OpenAlex
work also carries alongside its SDG tag resolves several of these cleanly.

Two passes, per direct user instruction ("first consider the simple lexical match... then
for the unmatched ones use your LLM smarts"):

1. Lexical: cascade_match.py's own exact/contains word-set matching (already used for
   OAX<->FOR2020 elsewhere in this project, reused as-is here, not reinvented) between each
   ambiguous goal's own candidate division labels -- a small, SDG-constrained pool, same
   pattern as this project's other `constrained_lexical` resolutions -- and every OAX
   subfield label. Field-level (26) labels were tried first and rejected: confirmed directly
   they're too generic/short to share real words with SEO2020's specific division names
   (raw character-level scoring was mostly coincidental noise, e.g. "Nursing"->
   "MANUFACTURING" at 0.60; subfield level (252) is what actually finds clean hits).

2. Manual: for candidates the lexical pass can't resolve -- either because none of an
   ambiguous goal's own divisions share exact words with any subfield (goals 8, 10's
   "DEFENCE"/"INDIGENOUS" side), or because a goal has NO division at all in the plain table
   to begin with (the 5 "orphan" goals: 1, 5, 6, 14, 17) -- reviewed all 252 OAX subfields
   against the relevant SEO2020 divisions directly and hand-picked plausible ones. Two
   genuine dead ends confirmed and left with no override at all, not a forced guess:
   "EXPANDING KNOWLEDGE" (division 28, one of goal 9's candidates) is ANZSRC's
   basic/curiosity-driven-research catch-all, an intent category with no subject-matter
   content by definition; "DEFENCE" (division 14, one of goal 16's candidates) and
   "INDIGENOUS" (division 21, one of goal 10's candidates) have no OpenAlex academic-subject
   analog at all (OpenAlex's classification has no military/security or Indigenous-studies
   subfield). All three correctly fall through to the plain multi-alternate default at query
   time rather than being forced to a bad guess here.
"""

from __future__ import annotations

import pandas as pd

from .cascade_match import exact_match_words
from .hierarchy import write_csv
from .paths import CANONICAL_DIR, HUB_DIR

COLUMNS = [
    "sdg_code", "sdg_label", "oax_subfield_code", "oax_subfield_label",
    "seo2020_division_code", "seo2020_division_label", "match_method", "confidence", "notes",
]

# Manual pass: (sdg_code, oax_subfield_code, oax_subfield_label, seo2020_division_code,
# confidence, notes). Confidence reflects how directly each subfield indicates the target
# division -- genuinely weak/stretch calls are kept low deliberately, not rounded up.
MANUAL_OVERRIDES: list[tuple[str, str, str, str, float, str]] = [
    ("2", "1103", "Animal Science and Zoology", "10", 0.9,
     "clear semantic fit (goal 2's other candidate, division 26, is already resolved "
     "lexically via 'Plant Science')"),
    ("8", "1409", "Tourism, Leisure and Hospitality Management", "11", 0.9, "clear semantic fit"),
    ("8", "2002", "Economics and Econometrics", "15", 0.8, "clear semantic fit"),
    ("10", "3316", "Cultural Studies", "13", 0.8, "clear semantic fit"),
    # goal 16's DEFENCE (14) and goal 10's INDIGENOUS (21): no OAX subfield analog exists at
    # all -- deliberately no entry, see module docstring.
    ("1", "3207", "Social Psychology", "13", 0.7, "broad fit; no subfield names poverty/welfare directly"),
    ("1", "3300", "General Social Sciences", "13", 0.7, "broad fit; no subfield names poverty/welfare directly"),
    ("5", "3318", "Gender Studies", "13", 0.8, "clear semantic fit"),
    ("6", "2312", "Water Science and Technology", "18", 0.8, "clear semantic fit"),
    ("14", "1104", "Aquatic Science", "18", 0.8, "clear semantic fit"),
    ("14", "1910", "Oceanography", "18", 0.8, "clear semantic fit"),
    ("14", "2212", "Ocean Engineering", "18", 0.7, "engineering angle, slightly less direct than the other two"),
    ("17", "3320", "Political Science and International Relations", "23", 0.5,
     "weak/stretch: this SDG goal is a meta/process goal about cooperation as a means, not a subject domain"),
]


def _lexical_pass(seo_sdg: pd.DataFrame, subfields: pd.DataFrame, sdg_label: dict[str, str]) -> list[dict]:
    groups = seo_sdg.groupby("sdg_code")[["seo2020_division_code", "seo2020_division_label"]].apply(
        lambda g: list(zip(g["seo2020_division_code"], g["seo2020_division_label"]))
    )
    ambiguous = {goal: divs for goal, divs in groups.items() if len(divs) > 1}

    rows = []
    for goal, divs in ambiguous.items():
        candidate_words = {(code, label): exact_match_words(label) for code, label in divs}
        for sf_code, sf_label in zip(subfields["code"], subfields["label"]):
            sf_words = exact_match_words(sf_label)
            if not sf_words:
                continue
            hits = [
                key for key, words in candidate_words.items()
                if words and (words == sf_words or words <= sf_words or sf_words <= words)
            ]
            if len(hits) != 1:
                continue  # no candidate, or ties even within this narrow pool -- skip, don't guess
            div_code, div_label = hits[0]
            is_exact = candidate_words[hits[0]] == sf_words
            rows.append({
                "sdg_code": goal, "sdg_label": sdg_label[goal],
                "oax_subfield_code": sf_code, "oax_subfield_label": sf_label,
                "seo2020_division_code": div_code, "seo2020_division_label": div_label,
                "match_method": "exact_match" if is_exact else "contains_match",
                "confidence": 1.0 if is_exact else 0.9,
                "notes": "",
            })
    return rows


def _manual_pass(division_label: dict[str, str], sdg_label: dict[str, str]) -> list[dict]:
    return [
        {
            "sdg_code": goal, "sdg_label": sdg_label[goal],
            "oax_subfield_code": sf_code, "oax_subfield_label": sf_label,
            "seo2020_division_code": div_code, "seo2020_division_label": division_label[div_code],
            "match_method": "manual_curated", "confidence": confidence, "notes": note,
        }
        for goal, sf_code, sf_label, div_code, confidence, note in MANUAL_OVERRIDES
    ]


def run() -> pd.DataFrame:
    seo_sdg = pd.read_csv(HUB_DIR / "seo2020_division_sdg.csv", dtype=str, keep_default_na=False)
    sdg = pd.read_csv(CANONICAL_DIR / "sdg.csv", dtype=str, keep_default_na=False)
    sdg_label = dict(zip(sdg["code"], sdg["label"]))
    subfields = pd.read_csv(CANONICAL_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    seo2020 = pd.read_csv(CANONICAL_DIR / "seo_2020.csv", dtype=str, keep_default_na=False)
    division_label = dict(zip(
        seo2020[seo2020["level"] == "division"]["code"], seo2020[seo2020["level"] == "division"]["label"]
    ))

    rows = _lexical_pass(seo_sdg, subfields, sdg_label) + _manual_pass(division_label, sdg_label)
    df = pd.DataFrame(rows, columns=COLUMNS)
    write_csv(df, HUB_DIR / "sdg_oax_subfield_to_seo2020.csv", ["sdg_code", "oax_subfield_code"])
    return df


if __name__ == "__main__":
    df = run()
    print(f"{len(df)} rows written to sdg_oax_subfield_to_seo2020.csv")
    print(df["match_method"].value_counts())
    print(df[["sdg_code", "oax_subfield_label", "seo2020_division_label", "match_method", "confidence"]].to_string(index=False))
