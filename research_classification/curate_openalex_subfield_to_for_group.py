"""OpenAlex subfield (252) -> FOR group (213), algorithmic via cascade_match's tokenizer,
exact-match-first cascade, and raw bag-overlap scoring (see cascade_match.py's module
docstring for the full rationale).

Searches ALL 213 groups, not just the ones under the subfield's parent field's already-
assigned division -- found directly this session that constraining the pool to the parent
field's division silently walls off the correct answer whenever a subfield's true home is a
*different* division than its own field's: OAX subfield "Education" (3304) sits under field
33 "Social Sciences", whose field-level division is 44 HUMAN SOCIETY, so a division-
constrained search never even sees division 39 EDUCATION's groups (3901 "Curriculum and
pedagogy" etc.) -- exactly the kind of miss this whole rebuild exists to fix, not reproduce
one level down.

BUT only for subfields with enough of their own vocabulary to trust an open search --
gated by SOURCE_MIN_TOKENS_FOR_OPEN_SEARCH. Checked directly: opening the pool fully found
143 of 252 subfields "crossing" to a non-home division, and the ones with real topical
support turned out to all have large bags (Sociology and Political Science: 345 tokens,
Education: 170, Economics and Econometrics: 147, Anthropology: 53 ...) while the wrong ones
were all near-empty (Equine: 4 tokens landing on "Law in context" via 2 coincidentally
shared generic words; General Psychology: 4 tokens; Complementary and Manual Therapy: 7).
There's no score-based threshold that separates these -- a thin subfield's *best possible*
overlap with anything is small, genuine match or not -- so the gate is on the subfield's own
bag size instead: enough vocabulary to mean something across an open 213-group search, or
not enough, in which case the search stays constrained to the parent field's own
already-curated division (the safer, structurally-grounded default) the way it always did.
Subfields still below even the constrained pool's floor are left for direct manual
inspection (see _MANUAL_OVERRIDES) rather than another round of formula-tuning -- these are
exactly the cases with too little text for *any* automated method to trust itself on.

Unlike curate_openalex_for.py's division search (where fine-grained group candidates are
excluded from the bag-overlap step because a group's bag is always a strict subset of its own
parent division's), groups being compared here ARE the target granularity -- ordinary
peer-to-peer overlap, no subset-exclusion needed.

Top-scoring candidates are kept as rows (primary + a handful of ranked alternates,
`is_primary` flags the winner) -- resolver.py's generic lookup surfaces the runners-up as
`alternates` on the returned CanonicalResult. Capped at TOP_N_ALTERNATES per subfield.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import cascade_match as cm
from .hierarchy import BRIDGE_COLUMNS, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

MIN_OVERLAP = 2  # groups' bags are far smaller than divisions' -- a lower floor than
                 # cascade_match.MIN_OVERLAP is appropriate at this granularity
TOP_N_ALTERNATES = 8
SOURCE_MIN_TOKENS_FOR_OPEN_SEARCH = 25  # see module docstring: below this, stay constrained
                                         # to the parent field's own division

# Escape hatch for subfield/group pairs the cascade gets wrong -- filled in only after
# inspecting the real run's output. Found directly this session: certain FOR2020 groups
# (Literary studies 61 tokens, Clinical sciences 49, Crop and pasture production 43 --
# against a median group bag size of just 19) act as size-based "magnets" the same way
# division 40 ENGINEERING and division 45 did at the coarser level, absorbing genuinely
# unrelated subfields (Archeology, Conservation, Political Science...) purely by having more
# child fields' worth of vocabulary to coincidentally overlap with. Rather than another round
# of formula-tuning to chase this down statistically, these ~30 were identified by direct
# inspection of the full primary-pick list and corrected by hand -- exactly the "your LLM
# would get this right" sanity check these thin/noisy cases call for, not a cleverer score.
# subfield_code -> (for_group_code, notes)
_MANUAL_OVERRIDES: dict[str, tuple[str, str]] = {
    "1204": ("4301", "Archaeology -- landed on Architecture/Anthropology via generic overlap"),
    "3302": ("4301", "Archaeology -- landed on Architecture via generic overlap"),
    "2215": ("3302", "Building and Construction -- exact-fit group 'Building' exists but wasn't reached"),
    "2705": ("3201", "Cardiology and Cardiovascular Medicine -- exact-fit group exists"),
    "1706": ("4601", "Computer Science Applications -- general fit, was a Literary-studies-style false magnet hit"),
    "1206": ("4102", "Conservation -- ecological/environmental concept, not Literary studies"),
    "3604": ("4203", "Emergency Medical Services -- health services concept, not HR/industrial relations"),
    "2712": ("3205", "Endocrinology, Diabetes and Metabolism -- metabolomics is the closest real fit"),
    "3300": ("4499", "General Social Sciences -- division 44's own NEC catch-all, not Education"),
    "2306": ("3702", "Global and Planetary Change -- exact-fit 'Climate change science' exists"),
    "1207": ("5002", "History and Philosophy of Science -- exact-fit group exists"),
    "3310": ("4704", "Linguistics and Language -- exact-fit 'Linguistics' group exists"),
    "2214": ("4701", "Media Technology -- communication/media concept, not Curriculum and pedagogy"),
    "2728": ("3209", "Neurology -- exact-fit 'Neurosciences' group exists"),
    "2808": ("3209", "Neurology -- exact-fit 'Neurosciences' group exists"),
    "2729": ("3215", "Obstetrics and Gynecology -- exact-fit 'Reproductive medicine' group exists"),
    "3320": ("4408", "Political Science and International Relations -- exact-fit 'Political science' group exists"),
    "2742": ("4201", "Rehabilitation -- exact-fit 'Allied health and rehabilitation science' group exists"),
    "1711": ("4006", "Signal Processing -- communications engineering concept, not econometrics"),
    "3312": ("4410", "Sociology and Political Science -- Sociology is the lead concept; landed on Literary studies via generic overlap"),
    "3616": ("4201", "Speech and Hearing -- allied health concept, not urban and regional planning"),
    "1804": ("4905", "Statistics, Probability and Uncertainty -- exact-fit 'Statistics' group exists"),
    "3322": ("3304", "Urban Studies -- exact-fit 'Urban and regional planning' group exists"),
    "2312": ("3707", "Water Science and Technology -- exact-fit 'Hydrology' group exists"),
    "1104": ("3005", "Aquatic Science -- fisheries/aquatic concept, not animal production"),
    "2304": ("4105", "Environmental Chemistry -- pollution/contamination is the closest real fit"),
    "2310": ("4105", "Pollution -- exact-fit 'Pollution and contamination' group exists"),
    "2309": ("4104", "Nature and Landscape Conservation -- environmental management concept"),
    "3306": ("4299", "Health -- division 42's own NEC catch-all, not Sociology"),
    "1202": ("4303", "History -- exact-fit 'Historical studies' group exists"),
    "1209": ("4302", "Museology -- exact-fit 'Heritage, archive and museum studies' group exists"),
    "1213": ("3606", "Visual Arts and Performing Arts -- visual arts concept, not Literary studies"),
    "2736": ("3214", "Pharmacology -- exact-fit 'Pharmacology and pharmaceutical sciences' group exists"),
    "3004": ("3214", "Pharmacology -- exact-fit 'Pharmacology and pharmaceutical sciences' group exists"),
    "2717": ("3202", "Geriatrics and Gerontology -- general clinical concept, not pharmacology"),
    "1307": ("3101", "Cell Biology -- exact-fit 'Biochemistry and cell biology' group exists"),
    "1310": ("3205", "Endocrinology -- metabolomics is the closest real fit, not evolutionary biology"),
    "2307": ("3214", "Health, Toxicology and Mutagenesis -- toxicology/pharmacology concept"),
    "2737": ("3208", "Physiology (Medicine field) -- exact-fit 'Medical physiology' group exists"),
    "1712": ("4612", "Software -- exact-fit 'Software engineering' group exists"),
    "2105": ("4104", "Renewable Energy, Sustainability and the Environment -- environmental management concept"),
    "2212": ("4015", "Ocean Engineering -- exact-fit 'Maritime engineering' group exists"),
    "2612": ("4903", "Numerical Analysis -- exact-fit 'Numerical and computational mathematics' group exists"),
    "2613": ("4905", "Statistics and Probability -- exact-fit 'Statistics' group exists"),

    # Full audit of all 252 subfields (not just the below_floor gaps), done directly by
    # reading each subfield against its own candidate pool via audit_oax_for_bridges.py --
    # see TODO.md for the summary. Two kinds of fix below: (1) below_floor subfields promoted
    # to a real pick -- every one of the original 46 gaps -- and (2) non-below_floor subfields
    # where the cascade's weak/generic-word pick was clearly wrong once read against a
    # dedicated, exact-fit FOR2020 group the algorithm missed.
    "1108": ("3008", "Horticulture -- exact-fit 'Horticultural production' group exists, below_floor missed it"),
    "1109": ("3109", "Insect Science -- entomology is an animal-science/zoology concept, not evolutionary biology"),
    "1302": ("3101", "Aging -- cellular/molecular senescence; biochemistry and cell biology is the closest home absent a dedicated gerontology group"),
    "1313": ("3101", "Molecular Medicine -- molecular biology of disease; biochemistry and cell biology is the closest fit"),
    "1315": ("3101", "Structural Biology -- protein/molecular structure; core biochemistry and cell biology"),
    "1502": ("4003", "Bioengineering -- exact-fit 'Biomedical engineering' group exists, below_floor missed it"),
    "1503": ("4004", "Catalysis -- chemical engineering process concept"),
    "1506": ("4004", "Filtration and Separation -- chemical engineering unit operation"),
    "1603": ("3406", "Electrochemistry -- physical chemistry subdiscipline, not analytical chemistry"),
    "1800": ("3599", "General Decision Sciences -- generic catch-all subfield fits the division's own NEC group best"),
    "1803": ("3507", "Management Science and Operations Research -- a management discipline, not information systems"),
    "1904": ("3709", "Earth-Surface Processes -- geomorphology is physical geography, not atmospheric sciences"),
    "2100": ("4004", "General Energy -- generic energy catch-all; no engineering group fits better than another among 4004/4008/4017, kept the algorithm's own pick and just promoted it off below_floor"),
    "2103": ("4004", "Fuel Technology -- combustion/petrochemical process, matches chemical engineering's own energy-in-combustion field"),
    "2302": ("4102", "Ecological Modeling -- directly matches 'Ecological applications', not climate-change-specific"),
    "2406": ("3107", "Virology -- microbiology concept, matches sibling subfields Applied Microbiology and Microbiology"),
    "2506": ("4016", "Metals and Alloys -- materials engineering, matches sibling materials subfields"),
    "2508": ("4016", "Surfaces, Coatings and Films -- materials engineering, matches sibling materials subfields"),
    "2703": ("3202", "Anesthesiology and Pain Medicine -- generic clinical specialty, no dedicated group exists"),
    "2704": ("3205", "Biochemistry (Medicine field) -- exact-fit 'Medical biochemistry and metabolomics' group exists"),
    "2715": ("3202", "Gastroenterology -- generic clinical specialty, no dedicated group exists"),
    "2718": ("4203", "Health Informatics -- health information systems concept, closer fit than generic clinical sciences"),
    "2724": ("3202", "Internal Medicine -- generic clinical specialty, no dedicated group exists"),
    "2727": ("3202", "Nephrology -- generic clinical specialty, no dedicated group exists"),
    "2747": ("3204", "Transplantation -- transplant immunology/rejection, closest fit is Immunology"),
    "2748": ("3202", "Urology -- generic clinical specialty, no dedicated group exists"),
    "2803": ("3209", "Biological Psychiatry -- psychiatric neuroscience, matches field's own home"),
    "2807": ("3209", "Endocrine and Autonomic Systems -- autonomic nervous system regulation, a neuroscience concept"),
    "2809": ("3209", "Sensory Systems -- sensory neuroscience, matches field's own home"),
    "2910": ("4205", "Issues, ethics and legal aspects -- nursing practice concept, direct fit with field's own home group"),
    "2911": ("4205", "Leadership and Management -- nursing leadership, direct fit with field's own home group"),
    "2922": ("4205", "Research and Theory -- nursing research, direct fit with field's own home group"),
    "3002": ("3214", "Drug Discovery -- pharmacology/pharmaceutical sciences, matches sibling subfields"),
    "3005": ("3214", "Toxicology -- closely allied with pharmacology, matches division convention"),
    "3102": ("5103", "Acoustics and Ultrasonics -- classical/wave physics concept"),
    "3105": ("5199", "Instrumentation -- spans many physics subdisciplines, generic catch-all"),
    "3106": ("5107", "Nuclear and High Energy Physics -- exact-fit 'Particle and high energy physics' group exists, missed by a weak lexical pick"),
    "3108": ("5106", "Radiation -- nuclear/radiological physics concept"),
    "3200": ("5299", "General Psychology -- generic catch-all subfield fits the division's own NEC group best"),
    "3203": ("5203", "Clinical Psychology -- exact-fit 'Clinical and health psychology' group exists, missed by a weak lexical pick"),
    "3206": ("5202", "Neuropsychology and Physiological Psychology -- biological psychology concept"),
    "3307": ("4499", "Human Factors and Ergonomics -- no group fits well; division's own NEC catch-all rather than a spurious Criminology cross"),
    "3311": ("4499", "Safety Research -- no group fits well; division's own NEC catch-all rather than a spurious Economics cross"),
    "3402": ("3009", "Equine -- veterinary sciences, matches sibling subfield Small Animals' own pick"),
    "3603": ("4208", "Complementary and Manual Therapy -- exact-fit 'Traditional, complementary and integrative medicine' group exists"),
    "3608": ("4203", "Medical Terminology -- generic health-administration concept, closest available group"),
    "3612": ("4201", "Physical Therapy, Sports Therapy and Rehabilitation -- exact-fit 'Allied health and rehabilitation science' group, already the algorithm's own pick, just promoted off below_floor"),
}


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "openalex_subfield_to_for_group.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    topics = pd.read_csv(DATA_DIR / "openalex_topics.csv", dtype=str, keep_default_na=False)
    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_df = for_df[~for_df["code"].str.startswith("45")]  # division 45 excluded; own proxy mechanism
    field_to_division = pd.read_csv(SEEDS_DIR / "openalex_field_to_for_division.csv", dtype=str, keep_default_na=False)

    division_of_field = dict(zip(field_to_division["openalex_field_id"], field_to_division["for_division_code"]))
    group_label = dict(zip(for_df[for_df["level"] == "group"]["code"], for_df[for_df["level"] == "group"]["label"]))
    all_group_codes = list(group_label)
    groups_by_division: dict[str, list[str]] = {}
    for _, row in for_df[for_df["level"] == "group"].iterrows():
        groups_by_division.setdefault(row["parent_code"], []).append(row["code"])

    subfield_bags = cm.oax_subfield_bags(subfields, topics)
    group_bags = cm.for_group_texts(for_df)

    rows = []
    for _, sub in subfields.iterrows():
        subfield_id, subfield_name, field_id = sub["code"], sub["label"], sub["parent_code"]

        if subfield_id in _MANUAL_OVERRIDES:
            group_code, note = _MANUAL_OVERRIDES[subfield_id]
            rows.append(
                {
                    "openalex_subfield_id": subfield_id,
                    "openalex_subfield_name": subfield_name,
                    "for_group_code": group_code,
                    "for_group_label": group_label.get(group_code, ""),
                    "is_primary": True,
                    "confidence": 0.7,
                    "match_method": "manual_override",
                    "notes": note,
                }
            )
            continue

        subfield_words = cm.exact_match_words(subfield_name)
        group_words = {g: cm.exact_match_words(group_label[g]) for g in all_group_codes}
        exact_hits = {g for g, words in group_words.items() if subfield_words and words == subfield_words}

        if not exact_hits and subfield_words:
            contains_pool = {g: w for g, w in group_words.items() if not cm.is_nec_code(g)}
            contains_hit = cm.contains_match(subfield_words, contains_pool)
            if contains_hit is not None:
                exact_hits = {contains_hit}

        source_tokens = cm.tokenize_words(subfield_bags.get(subfield_id, ""))
        if len(source_tokens) >= SOURCE_MIN_TOKENS_FOR_OPEN_SEARCH:
            pool = all_group_codes
        else:
            pool = groups_by_division.get(division_of_field.get(field_id, ""), []) or all_group_codes

        scored = sorted(
            (
                (g, cm.bag_overlap(subfield_bags.get(subfield_id, ""), group_bags.get(g, "")))
                for g in pool
            ),
            key=lambda t: (t[1], not cm.is_nec_code(t[0])),  # tie -> non-NEC group ranks first
            reverse=True,
        )

        # Winner: a decisive exact match (if unique) always wins outright; otherwise the
        # top raw-overlap scorer. Either way, the rest of the sorted list becomes ranked
        # alternates.
        is_exact = len(exact_hits) == 1
        if is_exact:
            winner = next(iter(exact_hits))
            ranked = [winner] + [g for g, _ in scored if g != winner][:TOP_N_ALTERNATES]
        else:
            ranked = [g for g, _ in scored[: TOP_N_ALTERNATES + 1]]

        overlap_of = dict(scored)
        for i, group_code in enumerate(ranked):
            is_primary = i == 0
            if is_primary and is_exact and group_code == winner:
                confidence, method = 1.0, "exact_match"
            else:
                overlap = overlap_of.get(group_code, 0)
                confidence = round(min(1.0, overlap / len(source_tokens)), 3) if source_tokens else 0.0
                method = "constrained_lexical"
                if is_primary and overlap < MIN_OVERLAP:
                    # Nothing cleared even the low group-level floor -- still recorded (so
                    # resolver.py has *a* row to fall back to division-level from), but not
                    # trustworthy enough to call it a confident group-level pick.
                    confidence, method = 0.0, "below_floor"
            rows.append(
                {
                    "openalex_subfield_id": subfield_id,
                    "openalex_subfield_name": subfield_name,
                    "for_group_code": group_code,
                    "for_group_label": group_label.get(group_code, ""),
                    "is_primary": is_primary,
                    "confidence": confidence,
                    "match_method": method,
                    "notes": "",
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
                "source_code": r["openalex_subfield_id"],
                "source_label": r["openalex_subfield_name"],
                "system": "FOR",
                "canonical_code": r["for_group_code"],
                "canonical_label": r["for_group_label"],
                "canonical_level": "group",
                "is_primary": str(r["is_primary"]) in ("True", "true", "1"),
                "match_method": r["match_method"],
                "confidence": float(r["confidence"]),
                "notes": r["notes"],
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


if __name__ == "__main__":
    seed = run()
    print(f"seed rows: {len(seed)}, unique subfields covered: {seed['openalex_subfield_id'].nunique()} / 252")
    bridge = to_bridge(seed)
    write_csv(bridge, DATA_DIR / "bridge_openalex_for_group.csv", ["source_code"])
    print("bridge rows:", len(bridge))
    print("\nmatch_method breakdown (primary rows only):")
    print(seed[seed["is_primary"].astype(str) == "True"]["match_method"].value_counts())
