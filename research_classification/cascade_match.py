"""Generic exact-match-first, overlap-count-last-resort matcher for aligning OAX <-> FOR2020,
usable in either direction (an OAX field/subfield resolving to FOR2020, or a FOR2020
division/group resolving to OAX -- same algorithm, just supplied different inputs).

Why this replaces the label-only approaches used everywhere in this pipeline before it:
every prior OAX<->FOR2020 correspondence was built from bare labels (or a label plus
immediate children's labels), which is too thin a signal and produced concrete, checked
misses -- OAX field 15 "Chemical Engineering" never had the *possibility* of landing on
FOR2020 group 4004 "Chemical engineering" (the original hand-typed seed only ever considered
FOR2020 divisions); FOR2020 division 39 "EDUCATION" has no OAX field whose label mentions
education at all (OAX subfield 3304 "Education", 137 topics, sits nested under the
differently-named parent field "Social Sciences").

Two steps, in order (stop at the first that finds a decisive match):

1. Exact word-set match between the source's own label and every target candidate's label
   (both of the target scheme's granularities at once -- FOR2020: division + group; OAX:
   field + subfield). "Exact" means the two labels' stopword-filtered, AU/UK<->US
   spelling-normalized word SETS are identical -- not "share a word", not a similarity
   score. Rules out the tie-break failure found this session ("Engineering" {engineering}
   must not match "Aerospace engineering" {aerospace, engineering} -- different sets) while
   still catching real matches text-overlap scoring alone would miss or mis-rank.
2. If step 1 found nothing: raw word/stem SET-INTERSECTION SIZE between the source's bag
   (its own descendants' labels, nothing else) and each COARSE-level candidate's equivalent
   bag -- no ratio, no normalization. This is a deliberate correction, not a refinement, of
   several earlier ratio-based formulas tried this session (overlap coefficient, Jaccard,
   frequency-weighted multiset counts) that were all found to systematically favour whichever
   candidate had the *smaller* bag, sometimes badly (a 14-token group beating the correct
   214-token division; FOR2020 division 45 "Indigenous Studies", by far the largest bag of
   all 23 divisions, winning ratio-based comparisons it had no business winning purely by
   being huge). ANZSRC's and OpenAlex's classifications were built by expert committees who
   named things consistently at every level of their own hierarchy -- the count of literally
   shared vocabulary between two bags is the plain, human-legible signal that matters, not a
   statistically-normalized approximation of it. Only coarse-level candidates (FOR2020:
   division; OAX: field) are scored here -- a fine-grained candidate's bag is always a subset
   of its own parent's bag (its labels are counted again inside the parent's aggregate), so it
   can never win a raw-count comparison against its own parent and searching it only adds
   noise; genuine fine-grained answers are what step 1's exact match exists to catch.

Minimal stopwords, not the expanded domain-specific list used earlier this session. A real
committee-authored classification calls the same concept the same thing at every level
("Veterinary sciences" at group level, "Veterinary" at OAX field level) -- dropping words
like "sciences"/"studies"/"other" to force matches was working around that discipline rather
than trusting it, and specifically broke the NEC ("not elsewhere classified") distinction
("Other engineering" vs "Engineering") in an earlier version of this module. The list below
keeps only genuine grammatical connectors.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"

MIN_OVERLAP = 5  # below this raw intersection size, a bag-fallback match is noise, not signal
_COARSE_LEVELS = {"division", "field"}
_FINE_LEVELS = {"group", "subfield"}

# Genuine grammatical connectors only -- deliberately NOT the expanded, domain-specific list
# used elsewhere in this project historically (which also dropped "sciences"/"studies"/
# "other"/"not"/"elsewhere"/"classified"). See the module docstring for why.
MINIMAL_STOPWORDS = {
    "the", "and", "of", "in", "for", "to", "a", "an", "or", "on", "with", "by", "is", "as",
    "at", "from",
}

# Small, explicit AU/UK -> US spelling pairs covering research-domain vocabulary actually
# seen in ANZSRC (British/Australian spelling) vs OpenAlex (US-leaning) labels -- e.g.
# "Paediatrics" (FOR2020 group 3213) vs OpenAlex's "Pediatrics, Perinatology and Child
# Health" was invisible to every word-based check this session until this was added.
# Deliberately a word list, not a suffix rule (a blind "-our"->"-or" or "-ise"->"-ize" rule
# would also mangle unrelated words like "tour"/"hour" or "surprise"/"advertise", which
# aren't spelling variants at all).
_AU_US_SPELLING: dict[str, str] = {
    "paediatric": "pediatric", "paediatrics": "pediatrics",
    "colour": "color", "colours": "colors",
    "behaviour": "behavior", "behaviours": "behaviors", "behavioural": "behavioral",
    "organisation": "organization", "organisations": "organizations", "organisational": "organizational",
    "anaesthesia": "anesthesia", "anaesthetic": "anesthetic", "anaesthetics": "anesthetics",
    "haematology": "hematology", "haematological": "hematological",
    "oesophageal": "esophageal", "oesophagus": "esophagus",
    "gynaecology": "gynecology", "gynaecological": "gynecological",
    "paediatrician": "pediatrician",
    "programme": "program", "programmes": "programs",
    "centre": "center", "centres": "centers",
    "fibre": "fiber", "fibres": "fibers",
    "labour": "labor",
    "modelling": "modeling",
    "catalogue": "catalog", "catalogues": "catalogs",
    "analyse": "analyze", "analysing": "analyzing", "analysed": "analyzed",
    "specialise": "specialize", "specialised": "specialized", "specialisation": "specialization",
    "optimise": "optimize", "optimised": "optimized", "optimisation": "optimization",
    "recognise": "recognize", "recognised": "recognized",
    "utilise": "utilize", "utilised": "utilized", "utilisation": "utilization",
    "defence": "defense", "offence": "offense",
    "practise": "practice",
    "licence": "license",
    "travelling": "traveling", "traveller": "traveler",
    "counselling": "counseling", "counsellor": "counselor",
    "enrolment": "enrollment",
    "fulfilment": "fulfillment",
    "mould": "mold", "moulding": "molding",
    "plough": "plow",
    "sceptic": "skeptic", "sceptical": "skeptical",
    "tyre": "tire", "tyres": "tires",
    "kerb": "curb",
}


def _singularize(word: str) -> str:
    """Strip a plain plural suffix only -- "sciences" -> "science", "studies" -> "study" --
    not blind prefix truncation. Found directly: whole-word matching alone missed
    "Science"/"Sciences" pairs across level (e.g. OAX "Health Professions" bag containing
    "sciences" failing to line up with FOR2020 division label "HEALTH SCIENCES"'s "sciences"
    only because the source and target happened to use different grammatical number for the
    same word). A blind fixed-length prefix stem (tried earlier this session, e.g. 5-6 chars)
    risks exactly the collision this deliberately avoids: "organic"[:6] and
    "organisation"[:6] are identical prefixes despite being unrelated words."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "ches", "shes")) and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def tokenize_words(text: str) -> set[str]:
    """Lowercase, strip punctuation, apply AU/UK->US spelling normalization and plural
    singularization, drop only the minimal grammatical-connector stopwords. One tokenizer,
    used everywhere in this module -- for the exact word-SET match and for the bag-overlap
    SIZE count alike -- deliberately, so "the same thing is called the same thing" at every
    step, not just within the source classifications this module compares."""
    words = re.findall(r"[a-z]+", text.lower())
    normalized = (_singularize(_AU_US_SPELLING.get(w, w)) for w in words)
    return {w for w in normalized if w not in MINIMAL_STOPWORDS and len(w) > 2}


def bag_overlap(source_bag: str, cand_bag: str) -> int:
    """Raw count of shared words between two bags -- the size of the set intersection, no
    ratio, no normalization. See the module docstring for why this replaced overlap
    coefficient/Jaccard/frequency-weighted formulas tried earlier this session."""
    return len(tokenize_words(source_bag) & tokenize_words(cand_bag))


# Near-universal FOR2020 group-naming suffixes ("Forestry sciences", "Veterinary sciences",
# "Education studies") rather than real distinguishing content -- stripped ONLY for the
# exact-match comparison below, not from tokenize_words generally (they still count normally
# in bag-overlap scoring, where they're part of a division/group's real vocabulary rather
# than noise). Found directly: OAX subfield "Forestry" {forestry} and FOR2020 group "Forestry
# sciences" {forestry, science} are obviously the same concept, but plain set equality can't
# see it -- the extra word is exactly this classification-suffix pattern, not a specializing
# term like "aerospace" in "Aerospace engineering" (which correctly must NOT be treated as
# equal to bare "Engineering" -- that was the original tie-break bug this cascade exists to
# avoid). Words are post-singularization ("sciences" -> "science", "studies" -> "study").
_SUFFIX_ONLY_WORDS = {"science", "study"}


def exact_match_words(text: str) -> set[str]:
    """tokenize_words(), minus classification-suffix words -- used only for the exact-match
    step, so a source and candidate differing by nothing but "sciences"/"studies" still
    count as the same thing without loosening bag-overlap scoring's use of those words."""
    return tokenize_words(text) - _SUFFIX_ONLY_WORDS


def is_nec_code(code: str) -> bool:
    """ANZSRC's own "not elsewhere classified" convention -- a catch-all group/division
    ending "99" (e.g. "Other engineering"). Used to break ties away from these thin,
    generic-content catch-alls rather than toward them."""
    return code.endswith("99")


def contains_match(source_words: set[str], candidate_words: dict[str, set[str]]) -> str | None:
    """One label's word set is a proper subset of the other's, and exactly one candidate has
    this relationship with source_words -- the tier between exact equality and fuzzy
    fallback. Found directly by manual audit: "Paediatrics" {pediatric} vs OAX "Pediatrics,
    Perinatology and Child Health" {pediatric, perinatology, child, health} is obviously the
    same concept (the extra words are peer concepts folded into one compound OAX subfield,
    not a narrowing modifier), but set equality can't see it and raw bag-overlap let a
    bigger, unrelated candidate ("Clinical sciences") win instead purely on size. Requiring
    UNIQUENESS is what keeps this safe against the original tie-break bug ("Engineering"
    {engineering} must not match "Aerospace engineering" {aerospace, engineering}) without
    reintroducing it by hand: a genuinely specializing word (aerospace, automotive, civil...)
    is almost always shared by *several* sibling candidates (every "X engineering" group), so
    "engineering" alone is a subset of many candidates' word sets, not one -- correctly fails
    uniqueness and falls through. A word that's part of exactly one compound label (pediatric,
    zoology, architecture, biological+science...) uniquely identifies its match instead.
    """
    hits = [
        key for key, words in candidate_words.items()
        if words and source_words and words != source_words and (words <= source_words or source_words <= words)
    ]
    return hits[0] if len(hits) == 1 else None


# A candidate target: (code, label, level, bag_text)
Candidate = tuple[str, str, str, str]


def cascade_resolve(
    source_name: str,
    source_bag: str,
    candidates: list[Candidate],
) -> tuple[str, str, str, float, str, str] | None:
    """Resolve one source node against a pool of target candidates (spanning both of the
    target scheme's granularities together -- e.g. FOR2020 divisions + groups together, when
    source is OAX). Returns (code, label, level, confidence, match_method, notes), or None if
    nothing clears MIN_OVERLAP even at the bag-fallback step.

    1. Exact word-set match (suffix words aside) between source_name and each candidate's own
       label.
    1.5. Contains match (see contains_match()) -- one label's word set is a proper subset of
       the other's, uniquely, e.g. "Zoology" vs "Animal Science and Zoology".
    2. Raw bag-overlap SIZE (source_bag vs each COARSE-level candidate's own bag), last resort
       only -- fine-grained candidates are excluded here since a fine candidate's bag is
       always a subset of its own parent's (double-counted inside the parent's aggregate), so
       it can never win this comparison against its own parent and only adds noise against
       others; a genuine fine-grained answer is what step 1 exists to catch.
    """
    source_words = exact_match_words(source_name)
    candidate_words = {(c, l, lv): exact_match_words(l) for c, l, lv, _ in candidates}
    candidate_bags = {(c, l, lv): bag for c, l, lv, bag in candidates}
    if source_words:
        hits = [key for key, words in candidate_words.items() if words == source_words]
        if len(hits) == 1:
            code, label, level = hits[0]
            return code, label, level, 1.0, "exact_match", ""
        if len(hits) > 1 and len({key[1] for key in hits}) == 1:
            # Multiple candidates share the identical label TEXT, not just the same word
            # set -- a genuine same-named duplicate on the target side (found directly:
            # OpenAlex has "Genetics", "Physiology", "Microbiology", "Neurology",
            # "Pharmacology", "Archeology", and "Biochemistry" each appearing twice, under
            # two different parent fields -- silently blocking exact-match for the
            # corresponding FOR2020 groups until this was added, since len(hits)==2 failed
            # uniqueness even though both hits are literally the same name). The name match
            # is exact regardless of which instance wins, so break the tie by bag overlap
            # with source_bag instead of giving up and falling through to fuzzy matching.
            best = max(hits, key=lambda key: bag_overlap(source_bag, candidate_bags[key]))
            code, label, level = best
            return code, label, level, 1.0, "exact_match", ""

        # NEC ("not elsewhere classified") catch-all codes are excluded from contains-match
        # consideration -- found directly (self-test, matching FOR2020 against itself): ANZSRC's
        # "Other X, Y and Z" NEC groups structurally enumerate their siblings' words (e.g.
        # "Other agricultural, veterinary and food sciences" contains "Food sciences"'s and
        # "Veterinary sciences"'s words), so they're a systematic false-positive risk for this
        # tier specifically, the same underlying pattern the NEC penalty elsewhere guards against.
        contains_pool = {key: words for key, words in candidate_words.items() if not is_nec_code(key[0])}
        contains_hit = contains_match(source_words, contains_pool)
        if contains_hit is not None:
            code, label, level = contains_hit
            return code, label, level, 0.9, "contains_match", ""

    coarse = [(c, l, lv, bag) for c, l, lv, bag in candidates if lv in _COARSE_LEVELS]
    scored = sorted(
        ((c, l, lv, bag_overlap(source_bag, bag)) for c, l, lv, bag in coarse),
        key=lambda t: t[3], reverse=True,
    )
    if not scored or scored[0][3] < MIN_OVERLAP:
        return None
    code, label, level, overlap = scored[0]
    source_tokens = tokenize_words(source_bag)
    confidence = round(min(1.0, overlap / len(source_tokens)), 3) if source_tokens else 0.0
    return code, label, level, confidence, "constrained_lexical", ""


# -- shared text builders (FOR2020 side) ---------------------------------------------------
#
# Bags are built from the descriptors alone: FOR2020 field (6-digit) labels on this side,
# OAX topic labels on the other -- nothing else. Two things were tried and dropped:
# - ABS's Table 4 definition/exclusions prose: explanatory text written for human readers,
#   not part of the classification's actual structure, and wildly inconsistent in depth
#   (group 3902 "Education policy, sociology and philosophy"'s entire Table 4 entry just
#   restates the label word-for-word -- thin enough to distort ratio-based scoring, the same
#   underlying problem the raw-count switch above addresses more generally).
# - The node's own label and any intermediate group-level labels: the node's own label is
#   already used separately (the exact-match step), so including it again in the bag is
#   redundant; group-level labels don't add content beyond what their own child fields
#   already say, and just inflate bag size unevenly across divisions.
# Field-level labels are the classification's real descriptive content -- e.g. "Agricultural
# biotechnology diagnostics (incl. biosensors)" is specific, technical vocabulary in its own
# right, not a thin stand-in -- the direct FOR2020-side analogue of OAX's topic labels.
#
# FOR2020 division 45 (Indigenous Studies) is a known, deliberate structural exception --
# excluded by callers building candidate pools, not handled here. Its 320 fields, spanning
# ~18 themed groups that each restate the same ~6 themes across three separate populations
# (Aboriginal & Torres Strait Islander / Maori / Pacific Peoples), make it by far the largest
# bag of any division -- large enough to win raw-overlap comparisons on size alone regardless
# of topical relevance. It already has its own dedicated resolution mechanism
# (curate_for2020_division45_to_proxy.py); general-purpose candidate pools should simply not
# include it.


def for_division_texts(for_df: pd.DataFrame) -> dict[str, str]:
    """Division text = every descendant field's (6-digit) label, and nothing else -- see the
    module note above."""
    texts: dict[str, str] = {code: "" for code in for_df[for_df["level"] == "division"]["code"]}
    for _, row in for_df[for_df["level"] == "field"].iterrows():
        div_code = row["code"][:2]
        if div_code in texts:
            texts[div_code] += f" {row['label']}"
    return texts


def for_group_texts(for_df: pd.DataFrame) -> dict[str, str]:
    """Group text = every child field's (6-digit) label, and nothing else -- see the module
    note above."""
    groups = for_df[for_df["level"] == "group"]
    fields = for_df[for_df["level"] == "field"]
    texts: dict[str, str] = {code: "" for code in groups["code"]}
    for _, row in fields.iterrows():
        parent = row["parent_code"]
        if parent in texts:
            texts[parent] += f" {row['label']}"
    return texts


TOP_N_TOPICS = 30
SUBFIELD_SHARE_FLOOR = 0.35  # below this, prefer the coarser field-level consensus instead


def topic_rank_resolve(
    source_bag: str,
    topics_df: pd.DataFrame,
    subfields_df: pd.DataFrame,
    fields_df: pd.DataFrame,
    top_n: int = TOP_N_TOPICS,
) -> dict[str, object] | None:
    """FOR2020 -> OAX direction only (see module docstring for why this is asymmetric with
    the OAX -> FOR2020 direction, which uses cascade_resolve()'s bag-overlap scoring instead).

    Rather than aggregating every topic under a candidate OAX field/subfield into one big
    diluted bag and comparing bag-vs-bag (what cascade_resolve() does, and what this
    function deliberately does NOT do), this scores every one of OpenAlex's ~4,500 topics
    *individually* against source_bag (a FOR2020 division/group's field-level bag), keeping
    only the topics that actually overlap, ranks them, and looks at which OAX subfield/field
    the top N concentrate under. This is "what a human does" when classifying something --
    look at concrete specific examples and see where they cluster -- rather than merging
    everything into one number first.

    Each topic's own score is *topic-centric* overlap (overlap / topic's own token count, not
    source_bag's) -- deliberately asymmetric, since topics are tiny (typically 10-40 tokens)
    and source_bag is comparatively large; scoring the other way around would reintroduce the
    exact size-dilution problem this function exists to avoid. Unlike cascade_resolve()'s bag
    comparison (whole-classification bags, large enough that raw overlap SIZE is the honest
    signal), individual topics are small enough that a ratio is still the right shape here.

    Returns a dict with both subfield- and field-level winners (and their "share" among the
    top N, used as confidence) so the caller can decide granularity -- prefer the subfield
    answer if its share clears SUBFIELD_SHARE_FLOOR, else use the field-level consensus.
    Returns None if no topic overlaps source_bag at all.
    """
    source_tokens = tokenize_words(source_bag)
    if not source_tokens:
        return None

    scored: list[tuple[str, str, float]] = []
    for _, row in topics_df.iterrows():
        parent_subfield = row["parent_code"]
        topic_tokens = tokenize_words(row["label"])
        if not topic_tokens:
            continue
        overlap = len(topic_tokens & source_tokens)
        if overlap == 0:
            continue
        scored.append((row["code"], parent_subfield, overlap / len(topic_tokens)))
    if not scored:
        return None

    scored.sort(key=lambda t: -t[2])
    top = scored[:top_n]
    n = len(top)

    subfield_label = dict(zip(subfields_df["code"], subfields_df["label"]))
    field_of_subfield = dict(zip(subfields_df["code"], subfields_df["parent_code"]))
    field_label = dict(zip(fields_df["code"], fields_df["label"]))

    subfield_counts = Counter(parent for _tid, parent, _s in top)
    best_subfield, sf_count = subfield_counts.most_common(1)[0]

    field_counts = Counter(field_of_subfield.get(parent) for _tid, parent, _s in top)
    best_field, f_count = field_counts.most_common(1)[0]

    return {
        "subfield_code": best_subfield,
        "subfield_label": subfield_label.get(best_subfield, ""),
        "subfield_share": round(sf_count / n, 3),
        "field_code": best_field,
        "field_label": field_label.get(best_field, ""),
        "field_share": round(f_count / n, 3),
        "n_topics_considered": n,
    }


# -- shared text builders (OAX side) -------------------------------------------------------
#
# "Descriptor" and "label" are the same thing -- there is no separate rich-text source used
# here. The comparison is symmetric: FOR2020's field (6-digit) labels on one side, OAX's
# topic labels on the other -- both already rich, specific, technical text in their own
# right (e.g. "Carbon Nanotubes in Composites", "Science Education and Pedagogy"), both
# already present in the canonical tables (openalex_topics.csv's own `label` column).

def oax_field_bags(fields_df: pd.DataFrame, subfields_df: pd.DataFrame, topics_df: pd.DataFrame) -> dict[str, str]:
    """Field bag = every descendant topic's label (via subfield -> topic, two levels down),
    and nothing else -- no field/subfield labels mixed in, matching the FOR2020 side's
    for_division_texts()/for_group_texts()."""
    texts: dict[str, str] = {code: "" for code in fields_df["code"]}
    subfield_to_field = dict(zip(subfields_df["code"], subfields_df["parent_code"]))
    for _, row in topics_df.iterrows():
        field = subfield_to_field.get(row["parent_code"])
        if field in texts:
            texts[field] += f" {row['label']}"
    return texts


def oax_subfield_bags(subfields_df: pd.DataFrame, topics_df: pd.DataFrame) -> dict[str, str]:
    """Subfield bag = every child topic's label, and nothing else."""
    texts: dict[str, str] = {code: "" for code in subfields_df["code"]}
    for _, row in topics_df.iterrows():
        parent = row["parent_code"]
        if parent in texts:
            texts[parent] += f" {row['label']}"
    return texts
