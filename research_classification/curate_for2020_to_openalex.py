"""FOR2020 division/group -> OAX domain/field/subfield, ported from a hand-curated mapping
built (and independently used successfully) in an earlier, separate project:
data_untracked/EARLIER_FOR_OAX_analysis/build_for_oax_field_map.py. That script hardcoded
every FOR division -> OAX field, and every FOR2020 group -> OAX subfield, each with the human
rationale recorded inline, and enforced (at build time, there) that a group's subfield must
nest inside its division's own assigned field -- exactly the guarantee this module re-checks
below via _validate_nesting().

Replaces two prior, never-converged approaches to this same direction:
- build_leiden.py's old explode_for_divisions()/explode_for_groups()-based generation of
  these same six tables, which was NOT independent evidence the way it looked -- it derived a
  FOR node's OAX distribution by routing back through bridge_openalex_for(_group).csv, which
  is itself generated FROM the OAX field/subfield -> FOR seed. A FOR division's "empirical"
  OAX field was actually just "whichever field the reverse seed happened to pick," not real
  independent signal.
- An earlier version of this module using cascade_match's topic_rank_resolve() to score each
  FOR node against OpenAlex's ~4,500 individual topics -- repeatedly revised, never converged
  (see TODO.md's full account). The dict below replaces that scoring entirely; cascade_match
  is not used here at all.

FOR2020 division 45 (Indigenous Studies) is deliberately excluded from both dicts below, even
though the source script did cover it -- this project already has its own, separately
reviewed and confirmed resolution mechanism for division 45
(curate_for2020_division45_to_proxy.py), and resolver.py's lookup order tries the
division/group-centric tables built here BEFORE falling back to that proxy mechanism, so
including division 45 here would silently short-circuit it.

match_method="manual_curated" throughout, at confidence=1.0, pending review (see TODO.md):
this is a deliberate, recorded judgment call, not a statistically-derived estimate -- except
for the division-level SUBFIELD table, which has no direct entry in the source dict (only
division->field and group->subfield were curated there) and is instead derived by an equal-
weight majority vote over the division's own (now independently-curated) groups' subfields --
genuinely "derived_empirical" over independent evidence, unlike the circular derivation it
replaces.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from .hierarchy import write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"

# 22 FOR2020 divisions -> OAX field name (division 45 excluded, see module docstring).
FIELD_BY_DIVISION: dict[str, str] = {
    "30": "Agricultural and Biological Sciences",
    "31": "Agricultural and Biological Sciences",
    "32": "Medicine",
    # Reassigned from "Arts and Humanities" (the legacy dict's original pick) to "Engineering"
    # during this session's review: OAX field 22 has exact-name subfields "Architecture"
    # (2216) and "Building and Construction" (2215) -- unreachable under Arts and Humanities
    # -- covering 2 of this division's 5 groups outright. The other 2 non-Other groups
    # (Design, Urban and regional planning) get their own cross-field overrides back toward
    # Arts and Humanities / Social Sciences instead, since neither fits Engineering well
    # either -- see GROUP_FIELD_OVERRIDE.
    "33": "Engineering",
    "34": "Chemistry",
    "35": "Business, Management and Accounting",
    "36": "Arts and Humanities",
    "37": "Earth and Planetary Sciences",
    "38": "Economics, Econometrics and Finance",
    "39": "Social Sciences",
    "40": "Engineering",
    "41": "Environmental Science",
    "42": "Medicine",
    "43": "Arts and Humanities",
    "44": "Social Sciences",
    "46": "Computer Science",
    "47": "Arts and Humanities",
    "48": "Social Sciences",
    "49": "Mathematics",
    "50": "Arts and Humanities",
    "51": "Physics and Astronomy",
    "52": "Psychology",
}

# 193 FOR2020 groups -> (OAX subfield_id, original rationale from the source script).
# Division 45's 20 groups excluded, see module docstring.
SUBFIELD_BY_GROUP: dict[str, tuple[str, str]] = {
    # --- Div 30 ---
    "3001": ("1100", "Agricultural biotechnology  (no Biotechnology in AgBio subfields)"),
    "3002": ("1102", "Agriculture, land and farm management -> Agronomy and Crop Science"),
    "3003": ("1103", "Animal production -> Animal Science and Zoology"),
    "3004": ("1102", "Crop and pasture production -> Agronomy and Crop Science"),
    "3005": ("1104", "Fisheries sciences -> Aquatic Science"),
    "3006": ("1106", "Food sciences -> Food Science"),
    "3007": ("1107", "Forestry sciences -> Forestry"),
    "3008": ("1108", "Horticultural production -> Horticulture"),
    "3009": ("1103", "Veterinary sciences -> Animal Science and Zoology"),
    "3099": ("1100", "Other -> General Agricultural and Biological Sciences"),
    # --- Div 31 ---
    "3101": ("1100", "Biochemistry and cell biology -> General (no Biochemistry in AgBio)"),
    "3102": ("1100", "Bioinformatics and computational biology -> General"),
    "3103": ("1105", "Ecology -> Ecology, Evolution, Behavior and Systematics"),
    "3104": ("1105", "Evolutionary biology -> Ecology, Evolution, Behavior and Systematics"),
    "3105": ("1100", "Genetics -> General (no Genetics in AgBio subfields)"),
    "3106": ("1100", "Industrial biotechnology -> General"),
    "3107": ("1100", "Microbiology -> General (no Microbiology in AgBio subfields)"),
    "3108": ("1110", "Plant biology -> Plant Science"),
    "3109": ("1103", "Zoology -> Animal Science and Zoology"),
    "3199": ("1100", "Other -> General"),
    # --- Div 32 ---
    "3201": ("2705", "Cardiovascular medicine and haematology -> Cardiology and Cardiovascular Medicine"),
    "3202": ("2724", "Clinical sciences -> Internal Medicine"),
    "3203": ("2724", "Dentistry -> Internal Medicine (Dentistry is OAX field 35, constrained to 27)"),
    "3204": ("2723", "Immunology -> Immunology and Allergy"),
    "3205": ("2704", "Medical biochemistry and metabolomics -> Biochemistry"),
    "3206": ("2716", "Medical biotechnology -> Genetics"),
    "3207": ("2726", "Medical microbiology -> Microbiology"),
    "3208": ("2737", "Medical physiology -> Physiology"),
    "3209": ("2728", "Neurosciences -> Neurology"),
    "3210": ("2712", "Nutrition and dietetics -> Endocrinology, Diabetes and Metabolism"),
    "3211": ("2730", "Oncology and carcinogenesis -> Oncology"),
    "3212": ("2731", "Ophthalmology and optometry -> Ophthalmology"),
    "3213": ("2735", "Paediatrics -> Pediatrics, Perinatology and Child Health"),
    "3214": ("2736", "Pharmacology and pharmaceutical sciences -> Pharmacology"),
    "3215": ("2743", "Reproductive medicine -> Reproductive Medicine"),
    "3299": ("2724", "Other -> Internal Medicine"),
    # --- Div 33 --- (reassigned to field 22 Engineering this session -- see FIELD_BY_DIVISION)
    "3301": ("2216", "Architecture -> Architecture (exact match, unreachable before the division-33 field reassignment)"),
    "3302": ("2215", "Building -> Building and Construction (exact-ish match, ditto)"),
    "3303": ("1213", "Design -> Visual Arts and Performing Arts (cross-field override, see GROUP_FIELD_OVERRIDE -- no Design analogue in Engineering)"),
    "3304": ("3322", "Urban and regional planning -> Urban Studies (cross-field override, see GROUP_FIELD_OVERRIDE -- Engineering has no planning-specific subfield)"),
    "3399": ("2200", "Other -> General Engineering"),
    # --- Div 34 ---
    "3401": ("1602", "Analytical chemistry -> Analytical Chemistry"),
    "3402": ("1604", "Inorganic chemistry -> Inorganic Chemistry"),
    "3403": ("1605", "Macromolecular and materials chemistry -> Organic Chemistry"),
    "3404": ("1605", "Medicinal and biomolecular chemistry -> Organic Chemistry"),
    "3405": ("1605", "Organic chemistry -> Organic Chemistry"),
    "3406": ("1606", "Physical chemistry -> Physical and Theoretical Chemistry"),
    "3407": ("1606", "Theoretical and computational chemistry -> Physical and Theoretical Chemistry"),
    "3499": ("1606", "Other -> Physical and Theoretical Chemistry"),
    # --- Div 35 ---
    "3501": ("1402", "Accounting, auditing and accountability -> Accounting"),
    "3502": ("1403", "Banking, finance and investment -> Business and International Management"),
    "3503": ("1403", "Business systems in context -> Business and International Management"),
    "3504": ("1403", "Commercial services -> Business and International Management"),
    "3505": ("1407", "Human resources and industrial relations -> Org Behavior and HRM"),
    "3506": ("1406", "Marketing -> Marketing"),
    "3507": ("1408", "Strategy, management and organisational behaviour -> Strategy and Management"),
    "3508": ("1409", "Tourism -> Tourism, Leisure and Hospitality Management"),
    "3509": ("1403", "Transportation, logistics and supply chains -> Business and International Management"),
    "3599": ("1403", "Other -> Business and International Management"),
    # --- Div 36 ---
    "3601": ("1213", "Art history, theory and criticism -> Visual Arts and Performing Arts"),
    "3602": ("1208", "Creative and professional writing -> Literature and Literary Theory"),
    "3603": ("1210", "Music -> Music"),
    "3604": ("1213", "Performing arts -> Visual Arts and Performing Arts"),
    "3605": ("1213", "Screen and digital media -> Visual Arts and Performing Arts"),
    "3606": ("1213", "Visual arts -> Visual Arts and Performing Arts"),
    "3699": ("1200", "Other -> General Arts and Humanities"),
    # --- Div 37 ---
    "3701": ("1902", "Atmospheric sciences -> Atmospheric Science"),
    "3702": ("1902", "Climate change science -> Atmospheric Science"),
    "3703": ("1906", "Geochemistry -> Geochemistry and Petrology"),
    "3704": ("1907", "Geoinformatics -> Geology"),
    "3705": ("1907", "Geology -> Geology"),
    "3706": ("1908", "Geophysics -> Geophysics"),
    "3707": ("1904", "Hydrology -> Earth-Surface Processes"),
    "3708": ("1910", "Oceanography -> Oceanography"),
    "3709": ("1904", "Physical geography and environmental geoscience -> Earth-Surface Processes"),
    "3799": ("1907", "Other -> Geology"),
    # --- Div 38 ---
    "3801": ("2002", "Applied economics -> Economics and Econometrics"),
    "3802": ("2002", "Econometrics -> Economics and Econometrics"),
    "3803": ("2002", "Economic theory -> Economics and Econometrics"),
    "3899": ("2000", "Other -> General Economics, Econometrics and Finance"),
    # --- Div 39 ---
    "3901": ("3304", "Curriculum and pedagogy -> Education"),
    "3902": ("3304", "Education policy, sociology and philosophy -> Education"),
    "3903": ("3304", "Education systems -> Education"),
    "3904": ("3304", "Specialist studies in education -> Education"),
    "3999": ("3304", "Other -> Education"),
    # --- Div 40 ---
    "4001": ("2202", "Aerospace engineering -> Aerospace Engineering"),
    "4002": ("2203", "Automotive engineering -> Automotive Engineering"),
    "4003": ("2204", "Biomedical engineering -> Biomedical Engineering"),
    "4004": ("2200", "Chemical engineering -> General Engineering (OAX ChemEng is field 15)"),
    "4005": ("2205", "Civil engineering -> Civil and Structural Engineering"),
    "4006": ("2208", "Communications engineering -> Electrical and Electronic Engineering"),
    "4007": ("2207", "Control engineering, mechatronics and robotics -> Control and Systems Engineering"),
    "4008": ("2208", "Electrical engineering -> Electrical and Electronic Engineering"),
    "4009": ("2208", "Electronics, sensors and digital hardware -> Electrical and Electronic Engineering"),
    "4010": ("2200", "Engineering practice and education -> General Engineering"),
    "4011": ("2200", "Environmental engineering -> General Engineering (Env Eng is field 23)"),
    "4012": ("2210", "Fluid mechanics and thermal engineering -> Mechanical Engineering"),
    "4013": ("2205", "Geomatic engineering -> Civil and Structural Engineering"),
    "4014": ("2209", "Manufacturing engineering -> Industrial and Manufacturing Engineering"),
    "4015": ("2212", "Maritime engineering -> Ocean Engineering"),
    "4016": ("2200", "Materials engineering -> General Engineering (Materials Sci is field 25)"),
    "4017": ("2210", "Mechanical engineering -> Mechanical Engineering"),
    "4018": ("2200", "Nanotechnology -> General Engineering"),
    "4019": ("2200", "Resources engineering and extractive metallurgy -> General Engineering"),
    "4099": ("2200", "Other -> General Engineering"),
    # --- Div 41 ---
    "4101": ("2306", "Climate change impacts and adaptation -> Global and Planetary Change"),
    "4102": ("2303", "Ecological applications -> Ecology"),
    "4103": ("2304", "Environmental biotechnology -> Environmental Chemistry"),
    "4104": ("2308", "Environmental management -> Management, Monitoring, Policy and Law"),
    "4105": ("2310", "Pollution and contamination -> Pollution"),
    "4106": ("2304", "Soil sciences -> Environmental Chemistry (Soil Sci is AgBio field 11)"),
    "4199": ("2303", "Other -> Ecology"),
    # --- Div 42 ---
    "4201": ("2742", "Allied health and rehabilitation science -> Rehabilitation"),
    "4202": ("2713", "Epidemiology -> Epidemiology"),
    "4203": ("2739", "Health services and systems -> Public Health"),
    "4204": ("2729", "Midwifery -> Obstetrics and Gynecology"),
    "4205": ("2724", "Nursing -> Internal Medicine"),
    "4206": ("2739", "Public health -> Public Health"),
    "4207": ("2732", "Sports science and exercise -> Orthopedics and Sports Medicine"),
    "4208": ("2707", "Traditional, complementary and integrative medicine -> Complementary medicine"),
    "4299": ("2724", "Other -> Internal Medicine"),
    # --- Div 43 ---
    "4301": ("1204", "Archaeology -> Archeology"),
    "4302": ("1209", "Heritage, archive and museum studies -> Museology"),
    "4303": ("1202", "Historical studies -> History"),
    "4399": ("1200", "Other -> General Arts and Humanities"),
    # --- Div 44 ---
    "4401": ("3314", "Anthropology -> Anthropology"),
    "4402": ("3312", "Criminology -> Sociology and Political Science"),
    "4403": ("3317", "Demography -> Demography"),
    "4404": ("3303", "Development studies -> Development"),
    "4405": ("3318", "Gender studies -> Gender Studies"),
    "4406": ("3305", "Human geography -> Geography, Planning and Development"),
    "4407": ("3321", "Policy and administration -> Public Administration"),
    "4408": ("3320", "Political science -> Political Science and International Relations"),
    "4409": ("3300", "Social work -> General Social Sciences"),
    "4410": ("3312", "Sociology -> Sociology and Political Science"),
    "4499": ("3300", "Other -> General Social Sciences"),
    # --- Div 46 ---
    "4601": ("1706", "Applied computing -> Computer Science Applications"),
    "4602": ("1702", "Artificial intelligence -> Artificial Intelligence"),
    "4603": ("1707", "Computer vision and multimedia computation -> Computer Vision and Pattern Recognition"),
    "4604": ("1705", "Cybersecurity and privacy -> Computer Networks and Communications"),
    "4605": ("1710", "Data management and data science -> Information Systems"),
    "4606": ("1712", "Distributed computing and systems software -> Software"),
    "4607": ("1704", "Graphics, augmented reality and games -> Computer Graphics and Computer-Aided Design"),
    "4608": ("1709", "Human-centred computing -> Human-Computer Interaction"),
    "4609": ("1710", "Information systems -> Information Systems"),
    "4610": ("1706", "Library and information studies -> Computer Science Applications"),
    "4611": ("1702", "Machine learning -> Artificial Intelligence"),
    "4612": ("1712", "Software engineering -> Software"),
    "4613": ("1703", "Theory of computation -> Computational Theory and Mathematics"),
    "4699": ("1706", "Other -> Computer Science Applications"),
    # --- Div 47 ---
    "4701": ("1200", "Communication and media studies -> General Arts and Humanities"),
    "4702": ("1200", "Cultural studies -> General Arts and Humanities"),
    "4703": ("1203", "Language studies -> Language and Linguistics"),
    "4704": ("1203", "Linguistics -> Language and Linguistics"),
    "4705": ("1208", "Literary studies -> Literature and Literary Theory"),
    "4799": ("1200", "Other -> General Arts and Humanities"),
    # --- Div 48 ---
    "4801": ("3308", "Commercial law -> Law"),
    "4802": ("3308", "Environmental and resources law -> Law"),
    "4803": ("3308", "International and comparative law -> Law"),
    "4804": ("3308", "Law in context -> Law"),
    "4805": ("3308", "Legal systems -> Law"),
    "4806": ("3308", "Private law and civil obligations -> Law"),
    "4807": ("3308", "Public law -> Law"),
    "4899": ("3308", "Other -> Law"),
    # --- Div 49 ---
    "4901": ("2604", "Applied mathematics -> Applied Mathematics"),
    "4902": ("2610", "Mathematical physics -> Mathematical Physics"),
    "4903": ("2605", "Numerical and computational mathematics -> Computational Mathematics"),
    "4904": ("2602", "Pure mathematics -> Algebra and Number Theory"),
    "4905": ("2613", "Statistics -> Statistics and Probability"),
    "4999": ("2604", "Other -> Applied Mathematics"),
    # --- Div 50 ---
    "5001": ("1211", "Applied ethics -> Philosophy"),
    "5002": ("1207", "History and philosophy of specific fields -> History and Philosophy of Science"),
    "5003": ("1211", "Philosophy -> Philosophy"),
    "5004": ("1212", "Religious studies -> Religious studies"),
    "5005": ("1212", "Theology -> Religious studies"),
    "5099": ("1200", "Other -> General Arts and Humanities"),
    # --- Div 51 ---
    "5101": ("3103", "Astronomical sciences -> Astronomy and Astrophysics"),
    "5102": ("3107", "Atomic, molecular and optical physics -> Atomic and Molecular Physics, and Optics"),
    "5103": ("3109", "Classical physics -> Statistical and Nonlinear Physics"),
    "5104": ("3104", "Condensed matter physics -> Condensed Matter Physics"),
    "5105": ("3108", "Medical and biological physics -> Radiation"),
    "5106": ("3106", "Nuclear and plasma physics -> Nuclear and High Energy Physics"),
    "5107": ("3106", "Particle and high energy physics -> Nuclear and High Energy Physics"),
    "5108": ("3104", "Quantum physics -> Condensed Matter Physics"),
    "5109": ("3103", "Space sciences -> Astronomy and Astrophysics"),
    "5110": ("3105", "Synchrotrons and accelerators -> Instrumentation"),
    "5199": ("3102", "Other -> Acoustics and Ultrasonics"),
    # --- Div 52 ---
    "5201": ("3202", "Applied and developmental psychology -> Applied Psychology"),
    "5202": ("3206", "Biological psychology -> Neuropsychology and Physiological Psychology"),
    "5203": ("3203", "Clinical and health psychology -> Clinical Psychology"),
    "5204": ("3205", "Cognitive and computational psychology -> Experimental and Cognitive Psychology"),
    "5205": ("3207", "Social and personality psychology -> Social Psychology"),
    "5299": ("3200", "Other -> General Psychology"),
}

# Deliberate, individually-reviewed exceptions to "every group's subfield must sit under its
# division's own assigned field" (see SUBFIELD_BY_GROUP above and _validate_nesting below).
# Found during this session's falsification-driven review: a division's single assigned OAX
# field is right for MOST of its groups, but a handful of specific groups are individually a
# textbook-exact fit for a *different* OAX field entirely (its own dedicated OAX field, often
# with an identically-named subfield) -- forcing them to stay under the division's field would
# mean picking a strictly worse subfield when a strictly better one is sitting right there.
# Reassigning the WHOLE division's field to fix these would just break every OTHER group in
# that division, which already fits the division's own field well. The break with the
# ASJC-style field/subfield nesting convention is intentional and known -- confirmed directly
# by the user as an acceptable trade-off, not an oversight.
# group_code -> (subfield_id, rationale)
GROUP_FIELD_OVERRIDE: dict[str, tuple[str, str]] = {
    # Div 31 Biological Sciences (division field: 11 Agricultural and Biological Sciences) --
    # these 5 groups are textbook Biochemistry/Genetics/Molecular-Biology or Microbiology
    # concepts with their own OAX field 13 / field 24 home; the division's other 4 groups
    # (Ecology, Evolutionary biology, Plant biology, Zoology) genuinely do fit field 11 and
    # keep their original mapping unchanged.
    "3101": ("1303", "Biochemistry and cell biology -> Biochemistry (field 13, exact-ish; field 11 has no Biochemistry subfield)"),
    "3102": ("1312", "Bioinformatics and computational biology -> Molecular Biology (field 13; closest available, imperfect -- no dedicated Bioinformatics subfield exists anywhere in OAX)"),
    "3105": ("1311", "Genetics -> Genetics (field 13, exact match)"),
    "3106": ("1305", "Industrial biotechnology -> Biotechnology (field 13, exact-ish match)"),
    "3107": ("2404", "Microbiology -> Microbiology (field 24, exact match)"),
    # Div 32 Biomedical and Clinical Sciences (division field: 27 Medicine) -- the one group
    # (of 15) with its own dedicated OAX field; every sibling group already fits Medicine well.
    "3203": ("3500", "Dentistry -> General Dentistry (field 35, exact match)"),
    # Div 33 Built Environment and Design (division field reassigned to 22 Engineering this
    # session) -- these 2 groups don't fit Engineering, unlike their siblings Architecture/
    # Building/Other.
    "3303": ("1213", "Design -> Visual Arts and Performing Arts (field 12; no Design analogue anywhere in Engineering)"),
    "3304": ("3322", "Urban and regional planning -> Urban Studies (field 33, exact-ish match; better fit than any Engineering subfield)"),
    # Div 40 Engineering (division field: 22 Engineering) -- these 3 groups each have their
    # own dedicated OAX top-level field; every other group in this division (Aerospace,
    # Automotive, Civil, Electrical, Mechanical, etc.) already fits field 22 well.
    "4004": ("1508", "Chemical engineering -> Process Chemistry and Technology (field 15; closest available -- field 15 has no General Chemical Engineering subfield)"),
    "4011": ("2305", "Environmental engineering -> Environmental Engineering (field 23, exact match)"),
    "4016": ("2500", "Materials engineering -> General Materials Science (field 25, exact-ish match)"),
    # Div 42 Health Sciences (division field: 27 Medicine) -- the one group (of 9) with its
    # own dedicated OAX field.
    "4205": ("2922", "Nursing -> Research and Theory (field 29; closest available -- field 29 has no General Nursing subfield, only narrow subtopics)"),
    # Div 46 Information and Computing Sciences (division field: 17 Computer Science) --
    # found during review, not part of the originally-flagged batch: field 33 has a subfield
    # literally named "Library and Information Sciences," a much better fit than the "Computer
    # Science Applications" fallback field 17 offered.
    "4610": ("3309", "Library and information studies -> Library and Information Sciences (field 33, exact-ish match)"),
    # Div 47 Language, Communication and Culture (division field: 12 Arts and Humanities) --
    # these 2 groups (of 6) have their own dedicated OAX Social Sciences subfields; Language
    # studies/Linguistics/Literary studies (the other 3 non-Other groups) already fit Arts and
    # Humanities well.
    "4701": ("3315", "Communication and media studies -> Communication (field 33, exact match)"),
    "4702": ("3316", "Cultural studies -> Cultural Studies (field 33, exact match)"),
}


def _validate_nesting(field_id_by_name: dict[str, str], subfield_parent_field: dict[str, str]) -> None:
    """Re-check, against CURRENT schema, the constraint the source script enforced at its own
    build time: every group's subfield must sit under its division's own assigned field --
    except the deliberate, individually-reviewed exceptions in GROUP_FIELD_OVERRIDE."""
    errors = []
    for group_code, (subfield_id, _note) in SUBFIELD_BY_GROUP.items():
        if group_code in GROUP_FIELD_OVERRIDE:
            continue
        div_code = group_code[:2]
        expected_field_name = FIELD_BY_DIVISION.get(div_code)
        if expected_field_name is None:
            continue
        expected_field_id = field_id_by_name.get(expected_field_name)
        actual_field_id = subfield_parent_field.get(subfield_id)
        if actual_field_id != expected_field_id:
            errors.append(
                f"  group {group_code}: subfield {subfield_id} is under field {actual_field_id}, "
                f"but division {div_code} maps to field {expected_field_id} ({expected_field_name})"
            )
    if errors:
        raise ValueError("FOR2020->OAX hierarchy violation:\n" + "\n".join(errors))


def _seeds() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build (or load, if already generated) the two seed CSVs -- the ported dict, in the
    same cache-guard shape as every other curate_*.py in this pipeline: present on disk means
    final, never regenerated."""
    division_seed_path = SEEDS_DIR / "for2020_division_to_openalex_field.csv"
    group_seed_path = SEEDS_DIR / "for2020_group_to_openalex_subfield.csv"
    if division_seed_path.exists() and group_seed_path.exists():
        return (
            pd.read_csv(division_seed_path, dtype=str, keep_default_na=False),
            pd.read_csv(group_seed_path, dtype=str, keep_default_na=False),
        )

    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    for_label = dict(zip(for_df["code"], for_df["label"]))
    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    subfields = pd.read_csv(DATA_DIR / "openalex_subfields.csv", dtype=str, keep_default_na=False)
    field_label_by_name = dict(zip(fields["label"], fields["code"]))
    field_row = dict(zip(fields["code"], zip(fields["label"], fields["parent_code"])))
    subfield_row = dict(zip(subfields["code"], zip(subfields["label"], subfields["parent_code"])))

    _validate_nesting(field_label_by_name, {code: parent for code, (_label, parent) in subfield_row.items()})

    division_rows = []
    for div_code, field_name in FIELD_BY_DIVISION.items():
        field_code = field_label_by_name[field_name]
        division_rows.append(
            {
                "for2020_code": div_code,
                "for2020_label": for_label.get(div_code, ""),
                "openalex_field_id": field_code,
                "openalex_field_label": field_name,
                "is_primary": True,
                "confidence": 1.0,
                "match_method": "manual_curated",
                "notes": "ported from data_untracked/EARLIER_FOR_OAX_analysis/build_for_oax_field_map.py",
                "reviewed": "",
            }
        )
    division_seed = pd.DataFrame(division_rows)
    write_csv(division_seed, division_seed_path, ["for2020_code"])

    group_rows = []
    for group_code, (default_subfield_id, default_note) in SUBFIELD_BY_GROUP.items():
        is_override = group_code in GROUP_FIELD_OVERRIDE
        subfield_id, note = GROUP_FIELD_OVERRIDE.get(group_code, (default_subfield_id, default_note))
        subfield_label, field_id = subfield_row[subfield_id]
        group_rows.append(
            {
                "for2020_code": group_code,
                "for2020_label": for_label.get(group_code, ""),
                "for2020_division_code": group_code[:2],
                "openalex_subfield_id": subfield_id,
                "openalex_subfield_label": subfield_label,
                "openalex_field_id": field_id,
                "openalex_field_label": field_row[field_id][0],
                "is_primary": True,
                "confidence": 1.0,
                "match_method": "manual_override" if is_override else "manual_curated",
                "notes": note,
                "reviewed": "",
            }
        )
    group_seed = pd.DataFrame(group_rows)
    write_csv(group_seed, group_seed_path, ["for2020_code"])

    return division_seed, group_seed


def run() -> dict[str, pd.DataFrame]:
    division_seed, group_seed = _seeds()

    fields = pd.read_csv(DATA_DIR / "openalex_fields.csv", dtype=str, keep_default_na=False)
    domains = pd.read_csv(DATA_DIR / "openalex_domains.csv", dtype=str, keep_default_na=False)
    domain_label = dict(zip(domains["code"], domains["label"]))
    field_domain = dict(zip(fields["code"], fields["parent_code"]))

    # -- group-level: subfield is direct (curated); field/domain are exact hierarchy walks up
    # from that one curated fact, so every group-level row is fully deterministic.
    group_subfield_rows, group_field_rows, group_domain_rows = [], [], []
    for _, r in group_seed.iterrows():
        group_subfield_rows.append({
            "for_group_code": r["for2020_code"], "for_group_label": r["for2020_label"],
            "openalex_subfield_id": r["openalex_subfield_id"], "openalex_subfield_label": r["openalex_subfield_label"],
            "is_primary": True, "share": 1.0, "match_method": r["match_method"],
        })
        group_field_rows.append({
            "for_group_code": r["for2020_code"], "for_group_label": r["for2020_label"],
            "openalex_field_id": r["openalex_field_id"], "openalex_field_label": r["openalex_field_label"],
            "is_primary": True, "share": 1.0, "match_method": r["match_method"],
        })
        domain_code = field_domain.get(r["openalex_field_id"], "")
        group_domain_rows.append({
            "for_group_code": r["for2020_code"], "for_group_label": r["for2020_label"],
            "openalex_domain_id": domain_code, "openalex_domain_label": domain_label.get(domain_code, ""),
            "is_primary": True, "share": 1.0, "match_method": r["match_method"],
        })

    # -- division-level field/domain: direct (curated) / exact walk-up, same as group-level.
    division_field_rows, division_domain_rows = [], []
    for _, r in division_seed.iterrows():
        division_field_rows.append({
            "for_division_code": r["for2020_code"], "for_division_label": r["for2020_label"],
            "openalex_field_id": r["openalex_field_id"], "openalex_field_label": r["openalex_field_label"],
            "is_primary": True, "share": 1.0, "match_method": r["match_method"],
        })
        domain_code = field_domain.get(r["openalex_field_id"], "")
        division_domain_rows.append({
            "for_division_code": r["for2020_code"], "for_division_label": r["for2020_label"],
            "openalex_domain_id": domain_code, "openalex_domain_label": domain_label.get(domain_code, ""),
            "is_primary": True, "share": 1.0, "match_method": r["match_method"],
        })

    # -- division-level subfield: no direct curated fact exists at this granularity (the
    # source dict only ever curated division->field and group->subfield). Derived instead by
    # an equal-weight majority vote over the division's own already-curated groups --
    # genuinely independent evidence now, unlike the circular derivation this replaces.
    division_label = dict(zip(division_seed["for2020_code"], division_seed["for2020_label"]))
    division_subfield_rows = []
    group_seed = group_seed.copy()
    group_seed["div"] = group_seed["for2020_division_code"]
    for div_code, grp in group_seed.groupby("div"):
        counts = Counter(grp["openalex_subfield_id"])
        total = len(grp)
        subfield_label_lookup = dict(zip(grp["openalex_subfield_id"], grp["openalex_subfield_label"]))
        for i, (subfield_id, n) in enumerate(counts.most_common()):
            division_subfield_rows.append({
                "for_division_code": div_code, "for_division_label": division_label.get(div_code, ""),
                "openalex_subfield_id": subfield_id, "openalex_subfield_label": subfield_label_lookup[subfield_id],
                "is_primary": i == 0, "share": round(n / total, 3), "match_method": "derived_empirical",
            })

    tables = {
        "for2020_division_openalex_domain": pd.DataFrame(division_domain_rows),
        "for2020_division_openalex_field": pd.DataFrame(division_field_rows),
        "for2020_division_openalex_subfield": pd.DataFrame(division_subfield_rows),
        "for2020_group_openalex_domain": pd.DataFrame(group_domain_rows),
        "for2020_group_openalex_field": pd.DataFrame(group_field_rows),
        "for2020_group_openalex_subfield": pd.DataFrame(group_subfield_rows),
    }
    for name, df in tables.items():
        key_col = "for_division_code" if "division" in name else "for_group_code"
        write_csv(df, DATA_DIR / f"{name}.csv", [key_col])
    return tables


if __name__ == "__main__":
    tables = run()
    for name, df in tables.items():
        print(name, len(df))
