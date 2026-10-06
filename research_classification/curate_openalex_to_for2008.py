"""OAX subfield (252) -> FOR2008 group (157), and OAX field (26) -> FOR2008 division (22).

OAX has a single topic layout, so this is a lateral mapping to a chosen FOR layout, not a
backward-in-time move -- the "forward in time only" rule concerns FOR/SEO vintages among
themselves (FOR2020 -> FOR2008 is deliberately still not exposed by resolve()).

Built the way TODO.md's OAX <-> FOR2020 history says works for this class of problem: three
cheap, independent signals produce a draft, then every row was reviewed directly and the
reviewed answer hardcoded below (GROUP_BY_SUBFIELD, DIVISION_BY_FIELD) -- no scoring formula
is tuned to make the draft converge. The three signals (see draft_signals()):

- forward: OAX subfield -> FOR2020 group (bridge_openalex_for_group.csv, algorithmic) ->
  FOR2008 group(s), via ABS's official "2020 FoR - 2008 FoR" leaf-level correspondence rolled
  up to group level by vote.
- reverse: FOR2020 groups whose hand-curated OAX subfield (hub/for2020_group_openalex_
  subfield.csv) is this subfield -> FOR2008 group(s), via the same official roll-up.
- lexical: the FOR2008 group whose label is most similar to the subfield's own label.

Confidence (match_method="manual_curated" for every primary): 1.0 when the reviewed pick
agrees with all three signals' top candidate, 0.9 with two, 0.8 with one, 0.7 with none (a
pure review judgment). Alternates are the other FOR2008 groups the two correspondence-based
signals put forward, is_primary=False, match_method="derived_empirical", confidence = their
combined vote share -- runners-up for a caller to inspect, not reviewed picks.
"""

from __future__ import annotations

import difflib
from collections import Counter

import openpyxl
import pandas as pd

from .hierarchy import BRIDGE_COLUMNS, write_csv
from .paths import BRIDGES_DIR, CANONICAL_DIR, HUB_DIR, RAW_DIR, SEEDS_DIR

ABS_XLSX = RAW_DIR / "abs_for_seo" / "anzsrc2020_anzsrc2008_correspondences.xlsx"

MAX_ALTERNATES = 4
REVIEWED_ON = "2026-10-06"

# 252 OAX subfields -> (FOR2008 group, review note). A note marks a departure from the forward
# draft signal; rows without one confirmed the draft on review.
GROUP_BY_SUBFIELD: dict[str, tuple[str, str]] = {
    "1100": ("0701", ""),  # General Agricultural and Biological Sciences -> Agriculture, Land and Farm Management
    "1102": ("0703", ""),  # Agronomy and Crop Science -> Crop and Pasture Production
    "1103": ("0608", ""),  # Animal Science and Zoology -> ZOOLOGY
    "1104": ("0704", ""),  # Aquatic Science -> Fisheries Sciences
    "1105": ("0602", ""),  # Ecology, Evolution, Behavior and Systematics -> ECOLOGY
    "1106": ("0908", ""),  # Food Science -> Food Sciences
    "1107": ("0705", ""),  # Forestry -> Forestry Sciences
    "1108": ("0706", ""),  # Horticulture -> Horticultural Production
    "1109": ("0608", ""),  # Insect Science -> ZOOLOGY
    "1110": ("0607", ""),  # Plant Science -> PLANT BIOLOGY
    "1111": ("0503", ""),  # Soil Science -> SOIL SCIENCES
    "1200": ("2005", ""),  # General Arts and Humanities -> Literary Studies
    "1202": ("2103", ""),  # History -> Historical Studies
    "1203": ("2004", ""),  # Language and Linguistics -> Linguistics
    "1204": ("2101", ""),  # Archeology -> Archaeology
    "1205": ("2005", ""),  # Classics -> Literary Studies
    "1206": ("2102", "Arts and Humanities 'Conservation' is heritage/art conservation (210202), not ecological conservation"),  # Conservation -> Curatorial and Related Studies
    "1207": ("2202", ""),  # History and Philosophy of Science -> History and Philosophy of Specific Fields
    "1208": ("2005", ""),  # Literature and Literary Theory -> Literary Studies
    "1209": ("2102", ""),  # Museology -> Curatorial and Related Studies
    "1210": ("1904", ""),  # Music -> Performing Arts and Creative Writing
    "1211": ("2203", ""),  # Philosophy -> Philosophy
    "1212": ("2204", ""),  # Religious studies -> Religion and Religious Studies
    "1213": ("1905", ""),  # Visual Arts and Performing Arts -> Visual Arts and Crafts
    "1302": ("0601", ""),  # Aging -> BIOCHEMISTRY AND CELL BIOLOGY
    "1303": ("0601", ""),  # Biochemistry -> BIOCHEMISTRY AND CELL BIOLOGY
    "1304": ("0299", "029901 Biological Physics is FOR2008's exact home for biophysics"),  # Biophysics -> OTHER PHYSICAL SCIENCES
    "1305": ("1003", "FOR2008 puts biotechnology under division 10 TECHNOLOGY; OAX's topics here are bioprocess-heavy"),  # Biotechnology -> Industrial Biotechnology
    "1306": ("1112", 'cancer research -> Oncology and Carcinogenesis'),  # Cancer Research -> Oncology and Carcinogenesis
    "1307": ("0601", ""),  # Cell Biology -> BIOCHEMISTRY AND CELL BIOLOGY
    "1308": ("1101", 'clinical biochemistry -> Medical Biochemistry and Metabolomics'),  # Clinical Biochemistry -> Medical Biochemistry and Metabolomics
    "1309": ("0608", ""),  # Developmental Biology -> ZOOLOGY
    "1310": ("1103", '110306 Endocrinology sits in Clinical Sciences'),  # Endocrinology -> Clinical Sciences
    "1311": ("0604", ""),  # Genetics -> GENETICS
    "1312": ("0601", ""),  # Molecular Biology -> BIOCHEMISTRY AND CELL BIOLOGY
    "1313": ("0601", ""),  # Molecular Medicine -> BIOCHEMISTRY AND CELL BIOLOGY
    "1314": ("0606", "biological physiology (under OAX's Biochemistry field); Medicine's own Physiology subfield 2737 -> 1116"),  # Physiology -> PHYSIOLOGY
    "1315": ("0601", ""),  # Structural Biology -> BIOCHEMISTRY AND CELL BIOLOGY
    "1402": ("1501", ""),  # Accounting -> Accounting, Auditing and Accountability
    "1403": ("1503", 'business/international management -> Business and Management, not Marketing'),  # Business and International Management -> Business and Management
    "1404": ("0806", ""),  # Management Information Systems -> Information Systems
    "1405": ("1503", '150307 Innovation and Technology Management'),  # Management of Technology and Innovation -> Business and Management
    "1406": ("1505", ""),  # Marketing -> Marketing
    "1407": ("1503", ""),  # Organizational Behavior and Human Resource Management -> Business and Management
    "1408": ("1503", ""),  # Strategy and Management -> Business and Management
    "1409": ("1506", ""),  # Tourism, Leisure and Hospitality Management -> Tourism
    "1410": ("1503", ""),  # Industrial relations -> Business and Management
    "1502": ("0903", ""),  # Bioengineering -> Biomedical Engineering
    "1503": ("0904", ""),  # Catalysis -> Chemical Engineering
    "1504": ("0904", 'chemical process safety -> Chemical Engineering, not Civil'),  # Chemical Health and Safety -> Chemical Engineering
    "1506": ("0904", ""),  # Filtration and Separation -> Chemical Engineering
    "1507": ("0915", '091504 Fluidisation and Fluid Mechanics, 091505 Heat and Mass Transfer Operations'),  # Fluid Flow and Transfer Processes -> Interdisciplinary Engineering
    "1508": ("0904", ""),  # Process Chemistry and Technology -> Chemical Engineering
    "1602": ("0301", ""),  # Analytical Chemistry -> ANALYTICAL CHEMISTRY
    "1603": ("0306", ""),  # Electrochemistry -> PHYSICAL CHEMISTRY (INCL. STRUCTURAL)
    "1604": ("0302", ""),  # Inorganic Chemistry -> INORGANIC CHEMISTRY
    "1605": ("0305", ""),  # Organic Chemistry -> ORGANIC CHEMISTRY
    "1606": ("0306", ""),  # Physical and Theoretical Chemistry -> PHYSICAL CHEMISTRY (INCL. STRUCTURAL)
    "1607": ("0306", ""),  # Spectroscopy -> PHYSICAL CHEMISTRY (INCL. STRUCTURAL)
    "1702": ("0801", ""),  # Artificial Intelligence -> Artificial Intelligence and Image Processing
    "1703": ("0802", ""),  # Computational Theory and Mathematics -> Computation Theory and Mathematics
    "1704": ("0801", '080103 Computer Graphics, not design practice'),  # Computer Graphics and Computer-Aided Design -> Artificial Intelligence and Image Processing
    "1705": ("0805", ""),  # Computer Networks and Communications -> Distributed Computing
    "1706": ("0803", ""),  # Computer Science Applications -> Computer Software
    "1707": ("0801", ""),  # Computer Vision and Pattern Recognition -> Artificial Intelligence and Image Processing
    "1708": ("1006", 'computer hardware/architecture, not building architecture'),  # Hardware and Architecture -> Computer Hardware
    "1709": ("0806", '080602 Computer-Human Interaction'),  # Human-Computer Interaction -> Information Systems
    "1710": ("0806", ""),  # Information Systems -> Information Systems
    "1711": ("0906", '090609 Signal Processing'),  # Signal Processing -> Electrical and Electronic Engineering
    "1712": ("0803", ""),  # Software -> Computer Software
    "1800": ("1599", ""),  # General Decision Sciences -> Other Commerce, Management, Tourism and Services
    "1802": ("0806", ""),  # Information Systems and Management -> Information Systems
    "1803": ("1503", ""),  # Management Science and Operations Research -> Business and Management
    "1804": ("0104", ""),  # Statistics, Probability and Uncertainty -> STATISTICS
    "1902": ("0401", ""),  # Atmospheric Science -> ATMOSPHERIC SCIENCES
    "1904": ("0406", ""),  # Earth-Surface Processes -> PHYSICAL GEOGRAPHY AND ENVIRONMENTAL GEOSCIENCE
    "1906": ("0402", ""),  # Geochemistry and Petrology -> GEOCHEMISTRY
    "1907": ("0403", ""),  # Geology -> GEOLOGY
    "1908": ("0404", ""),  # Geophysics -> GEOPHYSICS
    "1910": ("0405", ""),  # Oceanography -> OCEANOGRAPHY
    "1911": ("0403", ""),  # Paleontology -> GEOLOGY
    "1912": ("0201", ""),  # Space and Planetary Science -> ASTRONOMICAL AND SPACE SCIENCES
    "2000": ("1402", "general economics -> Applied Economics, FOR2008's broadest economics group"),  # General Economics, Econometrics and Finance -> Applied Economics
    "2002": ("1402", 'economics at large -> Applied Economics; Econometrics kept as an alternate'),  # Economics and Econometrics -> Applied Economics
    "2003": ("1502", ""),  # Finance -> Banking, Finance and Investment
    "2100": ("0906", "power and energy systems engineering (090607/090608) is FOR2008's main energy home"),  # General Energy -> Electrical and Electronic Engineering
    "2102": ("0906", ""),  # Energy Engineering and Power Technology -> Electrical and Electronic Engineering
    "2103": ("0904", ""),  # Fuel Technology -> Chemical Engineering
    "2104": ("0915", '091506 Nuclear Engineering'),  # Nuclear Energy and Engineering -> Interdisciplinary Engineering
    "2105": ("0906", '090608 Renewable Power and Energy Systems Engineering'),  # Renewable Energy, Sustainability and the Environment -> Electrical and Electronic Engineering
    "2200": ("0915", 'general engineering -> Interdisciplinary Engineering'),  # General Engineering -> Interdisciplinary Engineering
    "2202": ("0901", ""),  # Aerospace Engineering -> Aerospace Engineering
    "2203": ("0902", ""),  # Automotive Engineering -> Automotive Engineering
    "2204": ("0903", ""),  # Biomedical Engineering -> Biomedical Engineering
    "2205": ("0905", ""),  # Civil and Structural Engineering -> Civil Engineering
    "2206": ("0915", ""),  # Computational Mechanics -> Interdisciplinary Engineering
    "2207": ("0913", ""),  # Control and Systems Engineering -> Mechanical Engineering
    "2208": ("0906", ""),  # Electrical and Electronic Engineering -> Electrical and Electronic Engineering
    "2209": ("0910", ""),  # Industrial and Manufacturing Engineering -> Manufacturing Engineering
    "2210": ("0913", ""),  # Mechanical Engineering -> Mechanical Engineering
    "2211": ("0913", ""),  # Mechanics of Materials -> Mechanical Engineering
    "2212": ("0911", ""),  # Ocean Engineering -> Maritime Engineering
    "2213": ("0915", '091507 Risk Engineering'),  # Safety, Risk, Reliability and Quality -> Interdisciplinary Engineering
    "2214": ("0801", 'an engineering subfield whose OAX topics are mostly image processing; not humanities media studies'),  # Media Technology -> Artificial Intelligence and Image Processing
    "2215": ("1202", ""),  # Building and Construction -> Building
    "2216": ("1201", ""),  # Architecture -> Architecture
    "2302": ("0501", ""),  # Ecological Modeling -> ECOLOGICAL APPLICATIONS
    "2303": ("0602", ""),  # Ecology -> ECOLOGY
    "2304": ("0399", '039901 Environmental Chemistry (incl. Atmospheric Chemistry)'),  # Environmental Chemistry -> OTHER CHEMICAL SCIENCES
    "2305": ("0907", ""),  # Environmental Engineering -> Environmental Engineering
    "2306": ("0401", ""),  # Global and Planetary Change -> ATMOSPHERIC SCIENCES
    "2307": ("1115", ""),  # Health, Toxicology and Mutagenesis -> Pharmacology and Pharmaceutical Sciences
    "2308": ("0502", 'environmental management/monitoring/policy (050205), not urban planning'),  # Management, Monitoring, Policy and Law -> ENVIRONMENTAL SCIENCE AND MANAGEMENT
    "2309": ("0502", ""),  # Nature and Landscape Conservation -> ENVIRONMENTAL SCIENCE AND MANAGEMENT
    "2310": ("0502", ""),  # Pollution -> ENVIRONMENTAL SCIENCE AND MANAGEMENT
    "2311": ("0907", 'waste management -> Environmental Engineering (090703 Environmental Technologies)'),  # Waste Management and Disposal -> Environmental Engineering
    "2312": ("0406", ""),  # Water Science and Technology -> PHYSICAL GEOGRAPHY AND ENVIRONMENTAL GEOSCIENCE
    "2402": ("0605", ""),  # Applied Microbiology and Biotechnology -> MICROBIOLOGY
    "2403": ("1107", ""),  # Immunology -> Immunology
    "2404": ("0605", ""),  # Microbiology -> MICROBIOLOGY
    "2405": ("1108", "110803 Medical Parasitology; OAX's topics are mostly human parasitic disease"),  # Parasitology -> Medical Microbiology
    "2406": ("0605", ""),  # Virology -> MICROBIOLOGY
    "2500": ("0912", ""),  # General Materials Science -> Materials Engineering
    "2502": ("0903", '090301 Biomaterials'),  # Biomaterials -> Biomedical Engineering
    "2503": ("0912", ""),  # Ceramics and Composites -> Materials Engineering
    "2504": ("0912", '091205 Functional Materials'),  # Electronic, Optical and Magnetic Materials -> Materials Engineering
    "2505": ("0303", ""),  # Materials Chemistry -> MACROMOLECULAR AND MATERIALS CHEMISTRY
    "2506": ("0912", ""),  # Metals and Alloys -> Materials Engineering
    "2507": ("0912", ""),  # Polymers and Plastics -> Materials Engineering
    "2508": ("0912", ""),  # Surfaces, Coatings and Films -> Materials Engineering
    "2602": ("0101", 'algebra and number theory is pure mathematics (010101)'),  # Algebra and Number Theory -> PURE MATHEMATICS
    "2604": ("0102", ""),  # Applied Mathematics -> APPLIED MATHEMATICS
    "2605": ("0103", ""),  # Computational Mathematics -> NUMERICAL AND COMPUTATIONAL MATHEMATICS
    "2607": ("0101", '010104 Combinatorics and Discrete Mathematics sits in Pure Mathematics'),  # Discrete Mathematics and Combinatorics -> PURE MATHEMATICS
    "2608": ("0101", ""),  # Geometry and Topology -> PURE MATHEMATICS
    "2610": ("0105", ""),  # Mathematical Physics -> MATHEMATICAL PHYSICS
    "2611": ("0103", ""),  # Modeling and Simulation -> NUMERICAL AND COMPUTATIONAL MATHEMATICS
    "2612": ("0103", ""),  # Numerical Analysis -> NUMERICAL AND COMPUTATIONAL MATHEMATICS
    "2613": ("0104", ""),  # Statistics and Probability -> STATISTICS
    "2614": ("0802", 'theoretical computer science -> Computation Theory and Mathematics'),  # Theoretical Computer Science -> Computation Theory and Mathematics
    "2702": ("1103", ""),  # Anatomy -> Clinical Sciences
    "2703": ("1103", ""),  # Anesthesiology and Pain Medicine -> Clinical Sciences
    "2704": ("1101", ""),  # Biochemistry -> Medical Biochemistry and Metabolomics
    "2705": ("1102", ""),  # Cardiology and Cardiovascular Medicine -> Cardiorespiratory Medicine and Haematology
    "2706": ("1103", ""),  # Critical Care and Intensive Care Medicine -> Clinical Sciences
    "2707": ("1104", ""),  # Complementary and alternative medicine -> Complementary and Alternative Medicine
    "2708": ("1103", ""),  # Dermatology -> Clinical Sciences
    "2711": ("1103", ""),  # Emergency Medicine -> Clinical Sciences
    "2712": ("1103", '110306 Endocrinology; Medical Biochemistry and Metabolomics / Nutrition kept as alternates'),  # Endocrinology, Diabetes and Metabolism -> Clinical Sciences
    "2713": ("1117", ""),  # Epidemiology -> Public Health and Health Services
    "2714": ("1117", 'family/general practice -> 111717 Primary Health Care'),  # Family Practice -> Public Health and Health Services
    "2715": ("1103", ""),  # Gastroenterology -> Clinical Sciences
    "2716": ("1103", '110311 Medical Genetics (excl. Cancer Genetics)'),  # Genetics -> Clinical Sciences
    "2717": ("1103", ""),  # Geriatrics and Gerontology -> Clinical Sciences
    "2718": ("1117", ""),  # Health Informatics -> Public Health and Health Services
    "2720": ("1102", ""),  # Hematology -> Cardiorespiratory Medicine and Haematology
    "2721": ("1103", ""),  # Hepatology -> Clinical Sciences
    "2723": ("1107", ""),  # Immunology and Allergy -> Immunology
    "2724": ("1103", ""),  # Internal Medicine -> Clinical Sciences
    "2725": ("1103", ""),  # Infectious Diseases -> Clinical Sciences
    "2726": ("1108", "Microbiology under OAX's Medicine field -> Medical Microbiology"),  # Microbiology -> Medical Microbiology
    "2727": ("1103", ""),  # Nephrology -> Clinical Sciences
    "2728": ("1109", ""),  # Neurology -> Neurosciences
    "2729": ("1114", ""),  # Obstetrics and Gynecology -> Paediatrics and Reproductive Medicine
    "2730": ("1112", ""),  # Oncology -> Oncology and Carcinogenesis
    "2731": ("1113", ""),  # Ophthalmology -> Ophthalmology and Optometry
    "2732": ("1103", ""),  # Orthopedics and Sports Medicine -> Clinical Sciences
    "2733": ("1103", ""),  # Otorhinolaryngology -> Clinical Sciences
    "2734": ("1103", ""),  # Pathology and Forensic Medicine -> Clinical Sciences
    "2735": ("1114", ""),  # Pediatrics, Perinatology and Child Health -> Paediatrics and Reproductive Medicine
    "2736": ("1115", ""),  # Pharmacology -> Pharmacology and Pharmaceutical Sciences
    "2737": ("1116", ""),  # Physiology -> Medical Physiology
    "2738": ("1103", ""),  # Psychiatry and Mental health -> Clinical Sciences
    "2739": ("1117", ""),  # Public Health, Environmental and Occupational Health -> Public Health and Health Services
    "2740": ("1102", '110203 Respiratory Diseases sits in Cardiorespiratory Medicine and Haematology'),  # Pulmonary and Respiratory Medicine -> Cardiorespiratory Medicine and Haematology
    "2741": ("1103", ""),  # Radiology, Nuclear Medicine and Imaging -> Clinical Sciences
    "2742": ("1103", ""),  # Rehabilitation -> Clinical Sciences
    "2743": ("1114", ""),  # Reproductive Medicine -> Paediatrics and Reproductive Medicine
    "2745": ("1103", ""),  # Rheumatology -> Clinical Sciences
    "2746": ("1103", ""),  # Surgery -> Clinical Sciences
    "2747": ("1107", ""),  # Transplantation -> Immunology
    "2748": ("1103", ""),  # Urology -> Clinical Sciences
    "2802": ("1109", ""),  # Behavioral Neuroscience -> Neurosciences
    "2803": ("1109", ""),  # Biological Psychiatry -> Neurosciences
    "2804": ("1109", ""),  # Cellular and Molecular Neuroscience -> Neurosciences
    "2805": ("1109", ""),  # Cognitive Neuroscience -> Neurosciences
    "2806": ("1109", ""),  # Developmental Neuroscience -> Neurosciences
    "2807": ("1109", ""),  # Endocrine and Autonomic Systems -> Neurosciences
    "2808": ("1109", ""),  # Neurology -> Neurosciences
    "2809": ("1109", ""),  # Sensory Systems -> Neurosciences
    "2910": ("1110", ""),  # Issues, ethics and legal aspects -> Nursing
    "2911": ("1110", ""),  # Leadership and Management -> Nursing
    "2916": ("1111", ""),  # Nutrition and Dietetics -> Nutrition and Dietetics
    "2922": ("1110", ""),  # Research and Theory -> Nursing
    "3002": ("1115", ""),  # Drug Discovery -> Pharmacology and Pharmaceutical Sciences
    "3003": ("1115", ""),  # Pharmaceutical Science -> Pharmacology and Pharmaceutical Sciences
    "3004": ("1115", ""),  # Pharmacology -> Pharmacology and Pharmaceutical Sciences
    "3005": ("1115", ""),  # Toxicology -> Pharmacology and Pharmaceutical Sciences
    "3102": ("0203", ""),  # Acoustics and Ultrasonics -> CLASSICAL PHYSICS
    "3103": ("0201", ""),  # Astronomy and Astrophysics -> ASTRONOMICAL AND SPACE SCIENCES
    "3104": ("0204", ""),  # Condensed Matter Physics -> CONDENSED MATTER PHYSICS
    "3105": ("0299", ""),  # Instrumentation -> OTHER PHYSICAL SCIENCES
    "3106": ("0202", ""),  # Nuclear and High Energy Physics -> ATOMIC, MOLECULAR, NUCLEAR, PARTICLE AND PLASMA PHYSICS
    "3107": ("0205", ""),  # Atomic and Molecular Physics, and Optics -> OPTICAL PHYSICS
    "3108": ("0299", 'applied/medical radiation physics (029903 Medical Physics, 029904 Instruments and Techniques)'),  # Radiation -> OTHER PHYSICAL SCIENCES
    "3109": ("0203", '020304 Thermodynamics and Statistical Physics'),  # Statistical and Nonlinear Physics -> CLASSICAL PHYSICS
    "3200": ("1701", 'general psychology -> Psychology'),  # General Psychology -> Psychology
    "3202": ("1701", ""),  # Applied Psychology -> Psychology
    "3203": ("1701", ""),  # Clinical Psychology -> Psychology
    "3204": ("1701", ""),  # Developmental and Educational Psychology -> Psychology
    "3205": ("1702", ""),  # Experimental and Cognitive Psychology -> Cognitive Sciences
    "3206": ("1701", ""),  # Neuropsychology and Physiological Psychology -> Psychology
    "3207": ("1701", ""),  # Social Psychology -> Psychology
    "3300": ("1699", ""),  # General Social Sciences -> Other Studies in Human Society
    "3302": ("2101", ""),  # Archeology -> Archaeology
    "3303": ("1604", ""),  # Development -> Human Geography
    "3304": ("1302", ""),  # Education -> Curriculum and Pedagogy
    "3305": ("1604", ""),  # Geography, Planning and Development -> Human Geography
    "3306": ("1117", 'health as a social science -> Public Health and Health Services'),  # Health -> Public Health and Health Services
    "3307": ("1701", '170107 Industrial and Organisational Psychology covers human factors'),  # Human Factors and Ergonomics -> Psychology
    "3308": ("1801", ""),  # Law -> Law
    "3309": ("0807", ""),  # Library and Information Sciences -> Library and Information Studies
    "3310": ("2004", ""),  # Linguistics and Language -> Linguistics
    "3311": ("1117", '111705 Environmental and Occupational Health and Safety'),  # Safety Research -> Public Health and Health Services
    "3312": ("1608", ""),  # Sociology and Political Science -> Sociology
    "3313": ("1507", ""),  # Transportation -> Transportation and Freight Services
    "3314": ("1601", ""),  # Anthropology -> Anthropology
    "3315": ("2001", ""),  # Communication -> Communication and Media Studies
    "3316": ("2002", ""),  # Cultural Studies -> Cultural Studies
    "3317": ("1603", ""),  # Demography -> Demography
    "3318": ("1699", ""),  # Gender Studies -> Other Studies in Human Society
    "3319": ("1603", ""),  # Life-span and Life-course Studies -> Demography
    "3320": ("1606", ""),  # Political Science and International Relations -> Political Science
    "3321": ("1605", ""),  # Public Administration -> Policy and Administration
    "3322": ("1205", ""),  # Urban Studies -> Urban and Regional Planning
    "3402": ("0707", ""),  # Equine -> Veterinary Sciences
    "3404": ("0707", ""),  # Small Animals -> Veterinary Sciences
    "3500": ("1105", ""),  # General Dentistry -> Dentistry
    "3504": ("1105", ""),  # Oral Surgery -> Dentistry
    "3505": ("1105", ""),  # Orthodontics -> Dentistry
    "3506": ("1105", 'periodontics is dentistry'),  # Periodontics -> Dentistry
    "3600": ("1117", ""),  # General Health Professions -> Public Health and Health Services
    "3603": ("1104", ""),  # Complementary and Manual Therapy -> Complementary and Alternative Medicine
    "3604": ("1103", '110305 Emergency Medicine'),  # Emergency Medical Services -> Clinical Sciences
    "3605": ("1117", '111711 Health Information Systems (incl. Surveillance)'),  # Health Information Management -> Public Health and Health Services
    "3607": ("1103", ""),  # Medical Laboratory Technology -> Clinical Sciences
    "3608": ("1117", ""),  # Medical Terminology -> Public Health and Health Services
    "3609": ("1103", '110321 Rehabilitation and Therapy (excl. Physiotherapy)'),  # Occupational Therapy -> Clinical Sciences
    "3611": ("1115", '111503 Clinical Pharmacy and Pharmacy Practice'),  # Pharmacy -> Pharmacology and Pharmaceutical Sciences
    "3612": ("1103", ""),  # Physical Therapy, Sports Therapy and Rehabilitation -> Clinical Sciences
    "3614": ("1103", '110320 Radiology and Organ Imaging'),  # Radiological and Ultrasound Technology -> Clinical Sciences
    "3616": ("1103", ""),  # Speech and Hearing -> Clinical Sciences
}

# 26 OAX fields -> (FOR2008 division, review note).
DIVISION_BY_FIELD: dict[str, tuple[str, str]] = {
    # Agricultural and Biological Sciences -> BIOLOGICAL SCIENCES
    "11": ("06", "subfields split between 06 and 07 (and 05/09); 06 kept to match the existing "
                 "OAX field 11 -> FOR2020 31 BIOLOGICAL SCIENCES mapping, 07 is the main alternate"),
    "12": ("20", ""),  # Arts and Humanities -> LANGUAGE, COMMUNICATION AND CULTURE
    "13": ("06", ""),  # Biochemistry, Genetics and Molecular Biology -> BIOLOGICAL SCIENCES
    "14": ("15", ""),  # Business, Management and Accounting -> COMMERCE, MANAGEMENT, TOURISM AND SERVICES
    "15": ("09", ""),  # Chemical Engineering -> ENGINEERING
    "16": ("03", ""),  # Chemistry -> CHEMICAL SCIENCES
    "17": ("08", ""),  # Computer Science -> INFORMATION AND COMPUTING SCIENCES
    "18": ("15", ""),  # Decision Sciences -> COMMERCE, MANAGEMENT, TOURISM AND SERVICES
    "19": ("04", ""),  # Earth and Planetary Sciences -> EARTH SCIENCES
    "20": ("14", ""),  # Economics, Econometrics and Finance -> ECONOMICS
    "21": ("09", ""),  # Energy -> ENGINEERING
    "22": ("09", ""),  # Engineering -> ENGINEERING
    "23": ("05", ""),  # Environmental Science -> ENVIRONMENTAL SCIENCES
    "24": ("06", ""),  # Immunology and Microbiology -> BIOLOGICAL SCIENCES
    "25": ("09", ""),  # Materials Science -> ENGINEERING
    "26": ("01", ""),  # Mathematics -> MATHEMATICAL SCIENCES
    "27": ("11", ""),  # Medicine -> MEDICAL AND HEALTH SCIENCES
    "28": ("11", ""),  # Neuroscience -> MEDICAL AND HEALTH SCIENCES
    "29": ("11", ""),  # Nursing -> MEDICAL AND HEALTH SCIENCES
    "30": ("11", ""),  # Pharmacology, Toxicology and Pharmaceutics -> MEDICAL AND HEALTH SCIENCES
    "31": ("02", ""),  # Physics and Astronomy -> PHYSICAL SCIENCES
    "32": ("17", ""),  # Psychology -> PSYCHOLOGY AND COGNITIVE SCIENCES
    "33": ("16", ""),  # Social Sciences -> STUDIES IN HUMAN SOCIETY
    "34": ("07", ""),  # Veterinary -> AGRICULTURAL AND VETERINARY SCIENCES
    "35": ("11", ""),  # Dentistry -> MEDICAL AND HEALTH SCIENCES
    "36": ("11", ""),  # Health Professions -> MEDICAL AND HEALTH SCIENCES
}


# -- signal inputs ----------------------------------------------------------


def _for2020_to_for2008_leaf() -> pd.DataFrame:
    """ABS's official FOR2020 -> FOR2008 leaf-level correspondence (sheet "2020 FoR - 2008
    FoR"). Codes come through as a mix of int and str in this sheet; leading zeros (FOR2008
    divisions 01-09) are restored to 6 digits."""
    ws = openpyxl.load_workbook(ABS_XLSX, data_only=True)["2020 FoR - 2008 FoR"]
    rows = []
    for row in ws.iter_rows(min_row=8, max_col=5, values_only=True):
        code_2020, _name_2020, code_2008 = row[0], row[1], row[2]
        if code_2020 is None or code_2008 is None:
            continue
        code_2020, code_2008 = str(code_2020).strip(), str(code_2008).strip()
        if not (code_2020.isdigit() and code_2008.isdigit()):
            continue
        rows.append({"for2020": code_2020.zfill(6), "for2008": code_2008.zfill(6)})
    return pd.DataFrame(rows)


def _rollup(leaf: pd.DataFrame, width: int) -> dict[str, Counter]:
    """FOR2020 prefix (division/group) -> Counter of FOR2008 prefixes at the same width. Each
    FOR2020 leaf contributes one vote in total, split evenly across its FOR2008 targets, so a
    leaf with many partial targets doesn't outvote a clean one-to-one leaf."""
    out: dict[str, Counter] = {}
    for code_2020, grp in leaf.groupby("for2020"):
        weight = 1.0 / len(grp)
        votes = out.setdefault(code_2020[:width], Counter())
        for code_2008 in grp["for2008"]:
            votes[code_2008[:width]] += weight
    return out


def _primary_map(path, key_col: str, value_col: str) -> dict[str, str]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df[df["is_primary"].isin(["True", "true"])]
    return dict(zip(df[key_col], df[value_col]))


_STOPWORDS = {"and", "of", "the", "in", "incl", "excl", "general", "other", "studies", "science", "sciences"}


def _words(label: str) -> set[str]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in label.lower())
    return {w.rstrip("s") for w in cleaned.split() if w not in _STOPWORDS}


def _lexical_best(label: str, candidates: dict[str, str]) -> tuple[str, float]:
    """Word-overlap (Jaccard over content words, crude plural stripping), character
    similarity as the tiebreak. Deliberately simple -- a draft signal, not a matcher."""
    words = _words(label)
    scored = []
    for code, cand_label in candidates.items():
        if cand_label.lower().startswith("other "):
            continue
        cand_words = _words(cand_label)
        union = words | cand_words
        jaccard = len(words & cand_words) / len(union) if union else 0.0
        char = difflib.SequenceMatcher(None, label.lower(), cand_label.lower()).ratio()
        scored.append((jaccard, char, code))
    jaccard, _char, code = max(scored)
    return (code, round(jaccard, 3)) if jaccard > 0 else ("", 0.0)


def _top(counter: Counter) -> str:
    # deterministic: highest vote, then lowest code
    return min(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0] if counter else ""


def _shares(counter: Counter) -> dict[str, float]:
    total = sum(counter.values())
    return {code: n / total for code, n in counter.items()} if total else {}


def draft_signals(level: str) -> pd.DataFrame:
    """level='subfield' (OAX subfield -> FOR2008 group) or 'field' (OAX field -> FOR2008
    division). One row per OAX code: each signal's top candidate plus the combined
    correspondence vote, for review and for computing primaries' agreement/confidence."""
    width, oax_file, for2008_level = (4, "openalex_subfields.csv", "group") if level == "subfield" else (2, "openalex_fields.csv", "division")
    oax = pd.read_csv(CANONICAL_DIR / oax_file, dtype=str, keep_default_na=False)
    for2008 = pd.read_csv(CANONICAL_DIR / "for_2008.csv", dtype=str, keep_default_na=False)
    for2008 = dict(zip(for2008.loc[for2008["level"] == for2008_level, "code"], for2008.loc[for2008["level"] == for2008_level, "label"]))
    rollup = _rollup(_for2020_to_for2008_leaf(), width)

    if level == "subfield":
        forward_for2020 = _primary_map(BRIDGES_DIR / "bridge_openalex_for_group.csv", "source_code", "canonical_code")
        reverse_hub = _primary_map(HUB_DIR / "for2020_group_openalex_subfield.csv", "for_group_code", "openalex_subfield_id")
    else:
        forward_for2020 = _primary_map(BRIDGES_DIR / "bridge_openalex_for.csv", "source_code", "canonical_code")
        reverse_hub = _primary_map(HUB_DIR / "for2020_division_openalex_field.csv", "for_division_code", "openalex_field_id")

    rows = []
    for code, label in zip(oax["code"], oax["label"]):
        forward = Counter(rollup.get(forward_for2020.get(code, ""), Counter()))
        reverse = Counter()
        for for2020_code, oax_code in reverse_hub.items():
            if oax_code == code:
                reverse.update(rollup.get(for2020_code, Counter()))
        lex_code, lex_score = _lexical_best(label, for2008)
        # each correspondence signal normalized to sum to 1, then averaged over the signals
        # that actually produced votes -- a share in [0, 1] for ranking alternates
        n_signals = bool(forward) + bool(reverse)
        combined = Counter(_shares(forward))
        combined.update(_shares(reverse))
        rows.append({
            "oax_code": code,
            "oax_label": label,
            "forward": _top(forward),
            "reverse": _top(reverse),
            "lexical": lex_code,
            "lexical_score": lex_score,
            "combined": {c: v / n_signals for c, v in combined.items()} if n_signals else {},
        })
    return pd.DataFrame(rows)


# -- seeds and bridges --------------------------------------------------------

_LEVELS = {
    # level: (reviewed dict, seed file, bridge file, FOR2008 level name)
    "subfield": (GROUP_BY_SUBFIELD, "openalex_subfield_to_for2008_group.csv", "bridge_openalex_for2008_group.csv", "group"),
    "field": (DIVISION_BY_FIELD, "openalex_field_to_for2008_division.csv", "bridge_openalex_for2008.csv", "division"),
}

_CONFIDENCE_BY_AGREEMENT = {3: 1.0, 2: 0.9, 1: 0.8, 0: 0.7}


def _build_seed(level: str) -> pd.DataFrame:
    reviewed, _seed_file, _bridge_file, for2008_level = _LEVELS[level]
    for2008 = pd.read_csv(CANONICAL_DIR / "for_2008.csv", dtype=str, keep_default_na=False)
    for2008_label = dict(zip(for2008["code"], for2008["label"]))
    signals = draft_signals(level)
    assert set(signals["oax_code"]) == set(reviewed), f"{level}: reviewed dict does not cover every OAX code"

    rows = []
    for _, s in signals.iterrows():
        pick, note = reviewed[s["oax_code"]]
        assert for2008_label.get(pick) and len(pick) == (4 if for2008_level == "group" else 2), (s["oax_code"], pick)
        agreeing = [name for name in ("forward", "reverse", "lexical") if s[name] == pick]
        rows.append({
            "oax_code": s["oax_code"], "oax_label": s["oax_label"],
            "for2008_code": pick, "for2008_label": for2008_label[pick],
            "is_primary": True, "confidence": _CONFIDENCE_BY_AGREEMENT[len(agreeing)],
            "match_method": "manual_curated", "signals_agreeing": "+".join(agreeing),
            "notes": note, "reviewed": REVIEWED_ON,
        })
        alternates = sorted(
            ((code, share) for code, share in s["combined"].items() if code != pick),
            key=lambda kv: (-kv[1], kv[0]),
        )[:MAX_ALTERNATES]
        for code, share in alternates:
            rows.append({
                "oax_code": s["oax_code"], "oax_label": s["oax_label"],
                "for2008_code": code, "for2008_label": for2008_label[code],
                "is_primary": False, "confidence": round(share, 3),
                "match_method": "derived_empirical", "signals_agreeing": "",
                "notes": "runner-up from the official FOR2020 -> FOR2008 correspondence vote", "reviewed": "",
            })
    return pd.DataFrame(rows)


def _seed(level: str) -> pd.DataFrame:
    """Cache-guarded like every other curate_*.py seed: present on disk means final. Delete
    the seed file to regenerate it after editing GROUP_BY_SUBFIELD / DIVISION_BY_FIELD."""
    path = SEEDS_DIR / _LEVELS[level][1]
    if path.exists():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    seed = _build_seed(level)
    seed = seed.sort_values(["oax_code", "is_primary", "confidence"], ascending=[True, False, False])
    seed.to_csv(path, index=False, encoding="utf-8")
    return seed


def to_bridge(seed: pd.DataFrame, level: str) -> pd.DataFrame:
    for2008_level = _LEVELS[level][3]
    return pd.DataFrame({
        "source_system": "OpenAlex",
        "source_code": seed["oax_code"],
        "source_label": seed["oax_label"],
        "system": "FOR2008",
        "canonical_code": seed["for2008_code"],
        "canonical_label": seed["for2008_label"],
        "canonical_level": for2008_level,
        "is_primary": seed["is_primary"],
        "match_method": seed["match_method"],
        "confidence": seed["confidence"],
        "notes": seed["notes"],
    }, columns=BRIDGE_COLUMNS)


def run() -> dict[str, pd.DataFrame]:
    bridges = {}
    for level, (_reviewed, _seed_file, bridge_file, _for2008_level) in _LEVELS.items():
        bridge = to_bridge(_seed(level), level)
        write_csv(bridge, BRIDGES_DIR / bridge_file, ["source_code", "canonical_code"])
        bridges[bridge_file.removesuffix(".csv")] = bridge
    return bridges


if __name__ == "__main__":
    for name, df in run().items():
        primaries = df[df["is_primary"].astype(str) == "True"]
        print(name, len(df), "rows,", len(primaries), "primaries; confidence:",
              primaries["confidence"].astype(float).value_counts().sort_index().to_dict())
