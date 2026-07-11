"""FOR2020 division 45 (Indigenous Studies) group -> non-45 FOR2020 proxy (group or division).

Division 45's content is overwhelmingly the *same* research concept as elsewhere in
FOR2020, just re-scoped to an Aboriginal & Torres Strait Islander, Maori, or Pacific
Peoples population/perspective -- its own labels make this explicit by construction:

    "Aboriginal and Torres Strait Islander " + <concept>   (e.g. "...archaeology")
    "Pacific Peoples " + <concept>
    "<Maori-language label> (Maori " + <concept> + ")"      (bilingual, English gloss last)

Division 45 is structured as exactly 6 themes x 3 populations (ATSI 4501-4506, Maori
4507-4512, Pacific 4513-4518, same thematic order each time -- confirmed directly against
for_2020.csv), plus two "Other Indigenous..." catch-all groups that don't fit the pattern:

- **4519** ("Other Indigenous data, methodologies and global Indigenous studies") is
  heterogeneous, not a themed sibling -- but 5 of its 8 fields are literally "Global
  Indigenous studies " + one of the 6 theme names, so they reuse that theme's own proxy
  directly. The remaining 3 fields are handled individually (see below); the bare group code
  and bare division 45 itself both default to the "culture, language and history" theme's
  proxy, the broadest reasonable landing spot.
- **4599** ("Other Indigenous studies") has no sub-structure at all -- one NEC field, no
  non-Indigenous analogue possible -- and stays permanently unmapped.

Two design iterations, both driven by concrete failures found while spot-checking real
output (same pipeline pattern as curate_openalex_subfield_to_for_group.py's documented
history):

1. First cut scored each of the 18 groups independently. Noisy and inconsistent: the three
   population-siblings for the same theme sometimes landed on different proxies, or one
   sibling cleared the confidence floor while the other two -- same underlying concept --
   didn't, purely from ANZSRC's own minor wording differences between the three group labels
   (e.g. ATSI's "environmental knowledges AND MANAGEMENT" vs Maori/Pacific's plain
   "environmental knowledges"). Fixed by BUCKETING the three siblings per theme and merging
   their stripped text into one richer bag-of-words before scoring once per theme -- 3x the
   signal, and the three populations of a theme now always agree by construction.
2. Bucketing alone still left two themes -- "sciences" and "peoples, society and community"
   -- picking a highest-scoring GROUP that was really just noise (top candidates for
   "sciences" were things like "Medical and biological physics" and "Oceanography": no
   candidate group scored meaningfully above the rest, i.e. no coherent winner). Both themes
   are, by ANZSRC's own design, multi-division in breadth (a "sciences" catch-all spanning
   physical/biological/computing/engineering topics; a "peoples, society and community"
   catch-all spanning commerce/law/architecture/anthropology) -- something FOR2020 itself
   splits across many separate divisions for the general population, so no single 4-digit
   group should ever represent them well. Fixed by scoring against DIVISION-level candidates
   too (each division's own pooled text is naturally the same scale as a merged theme
   bucket) and preferring division unless a group candidate wins decisively (>=0.15 above
   the best division score) -- a mechanical, not per-theme-tuned, rule that happens to
   correctly exclude both noisy cases while accepting the four genuinely well-matched themes.

Reuses the exact scoring machinery already proven for OpenAlex-subfield -> FOR-group
(_group_score/_name_score/_tokenize_with_bigrams: unigrams+bigrams, overlap coefficient,
name-match bonus, NEC penalty for codes ending "99") rather than inventing new scoring logic.

A confidence floor (CONFIDENCE_FLOOR) excludes any theme whose best (group-or-division)
match is still weak -- left unmapped (hard-fail) rather than forcing a bad guess, consistent
with this pipeline's standing policy of failing loudly over fabricating.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import io as rio

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "research_classification" / "data"
SEEDS_DIR = ROOT / "seeds"
FOR_XLSX = ROOT / "data_untracked" / "ABS_FOR_SEO" / "anzsrc2020_for.xlsx"

CONFIDENCE_FLOOR = 0.35
GROUP_PREFERENCE_MARGIN = 0.15  # group-level must beat the best division score by this much to win

# The 6 themes x 3 populations, confirmed directly against for_2020.csv's division-45 rows
# (thematic order is identical across all three populations). 4519/4599 excluded -- no
# sibling structure, no prefix/gloss pattern, genuinely Indigenous-specific.
_THEME_BUCKETS: dict[str, list[str]] = {
    "culture, language and history": ["4501", "4507", "4513"],
    "education": ["4502", "4508", "4514"],
    "environmental knowledges": ["4503", "4509", "4515"],
    "health and wellbeing": ["4504", "4510", "4516"],
    "peoples, society and community": ["4505", "4511", "4518"],
    "sciences": ["4506", "4512", "4517"],
}

_PREFIXES = ["Aboriginal and Torres Strait Islander ", "Pacific Peoples ", "Indigenous ", "Global Indigenous studies "]
_MAORI_GLOSS_RE = re.compile(r"\(M[aā]ori (.+?)\)\s*$")

# Group 4519 ("Other Indigenous data, methodologies and global Indigenous studies") is
# heterogeneous, not a themed sibling of 4501-4518 -- but 5 of its 8 fields ("Global
# Indigenous studies " + concept) are literally restatements of 5 of the 6 existing themes,
# so they reuse those themes' own proxy directly rather than being scored again.
_4519_FIELD_TO_THEME: dict[str, str] = {
    "451901": "culture, language and history",
    "451902": "environmental knowledges",
    "451903": "health and wellbeing",
    "451904": "peoples, society and community",
    "451905": "sciences",
}

# User-provided domain override. ANZSRC's own field labels for the "sciences" theme spread
# across many STEM subtopics (astronomy, computing, engineering, genomics...), and the
# algorithmic score found no coherent match anywhere in either candidate pool -- top hits
# were noise ("Medical and biological physics", "Oceanography"), no division or group scored
# decisively. In practice, Indigenous/Aboriginal "science" content is closely aligned with
# traditional ecological knowledge and environmental management, not spread evenly across
# ANZSRC's own STEM divisions -- confirmed by the user directly, overriding the algorithmic
# (floor-failing) result rather than leaving this theme hard-failing.
_MANUAL_OVERRIDES: dict[str, tuple[str, str, str, float]] = {
    # theme -> (proxy_code, proxy_label, proxy_level, confidence)
    "sciences": ("41", "ENVIRONMENTAL SCIENCES", "division", 0.7),
    # Algorithmic pick was group 4409 "Social work" (0.435) -- the highest score, but not
    # a good semantic fit for a theme whose fields span accounting/commerce/law/architecture/
    # anthropology, not just social work specifically. User-provided override: group 4406
    # "Human geography" is the better single representative for this population/place/
    # community-centred theme.
    "peoples, society and community": ("4406", "Human geography", "group", 0.7),
}


def _strip_indigenous_gloss(label: str) -> str:
    for prefix in _PREFIXES:
        if label.startswith(prefix):
            return label[len(prefix):].strip()
    m = _MAORI_GLOSS_RE.search(label)
    if m:
        return m.group(1).strip()
    return label


def _group_texts(for_df: pd.DataFrame, *, strip: bool) -> dict[str, str]:
    """Group text = the group's own Table 4 definition PLUS every child field's label --
    same construction as curate_openalex_subfield_to_for_group._group_texts. strip=True
    (division-45 source groups) removes the Indigenous prefix/gloss from every piece of
    text first, so the bag-of-words reflects only the underlying generic research concept."""
    defs = rio.read_definitions(FOR_XLSX, sheet_name="Table 4")
    groups = defs[defs["level"] == "group"].set_index("code")
    fields = for_df[for_df["level"] == "field"]

    def maybe_strip(text: str) -> str:
        return _strip_indigenous_gloss(text) if strip else text

    texts: dict[str, str] = {
        code: f"{maybe_strip(row['label'])} {maybe_strip(row['definition'])}"
        for code, row in groups.iterrows()
    }
    for _, row in fields.iterrows():
        parent = row["parent_code"]
        if parent in texts:
            texts[parent] += f" {maybe_strip(row['label'])}"
    return texts


def _division_texts(for_df: pd.DataFrame) -> dict[str, str]:
    """Division text = the division's own Table 4 definition PLUS every descendant group's
    AND field's label -- the division-level analogue of _group_texts, same construction."""
    defs = rio.read_definitions(FOR_XLSX, sheet_name="Table 4")
    divisions = defs[defs["level"] == "division"].set_index("code")
    texts: dict[str, str] = {code: f"{row['label']} {row['definition']}" for code, row in divisions.iterrows()}
    for _, row in for_df[for_df["level"].isin(["group", "field"])].iterrows():
        div_code = row["code"][:2]
        if div_code in texts:
            texts[div_code] += f" {row['label']}"
    return texts


def run() -> pd.DataFrame:
    seed_path = SEEDS_DIR / "for2020_division45_group_to_proxy.csv"
    if seed_path.exists():
        return pd.read_csv(seed_path, dtype=str, keep_default_na=False)

    # Deferred: this scoring path only runs the one time the seed doesn't exist yet. Imported
    # lazily (not at module load time) so a broken/renamed helper in that module can't crash
    # every import of this one -- this happened in practice: _group_score no longer exists at
    # module scope in curate_openalex_subfield_to_for_group.py after its cascade_match
    # migration, breaking this import even though the seed already exists and this code path
    # never runs. See TODO.md: migrating this scorer onto cascade_match's shared helpers is
    # separately-tracked, not-yet-started work -- this lazy import just stops the unrelated
    # crash without touching the already-reviewed division-45 proxy logic itself.
    from .curate_openalex_subfield_to_for_group import _group_score

    for_df = pd.read_csv(DATA_DIR / "for_2020.csv", dtype=str, keep_default_na=False)
    group_rows = for_df[for_df["level"] == "group"]
    division_rows = for_df[for_df["level"] == "division"]
    group_label = dict(zip(group_rows["code"], group_rows["label"]))
    division_label = dict(zip(division_rows["code"], division_rows["label"]))

    candidate_groups = sorted(c for c in group_label if not c.startswith("45"))
    candidate_divisions = sorted(c for c in division_label if c != "45")
    source_texts = _group_texts(for_df, strip=True)
    group_texts = _group_texts(for_df, strip=False)
    division_texts = _division_texts(for_df)

    def add_row(src: str, src_label: str, theme: str, proxy_code: str, proxy_label: str, proxy_level: str, score: float) -> None:
        rows.append(
            {
                "for2020_source_code": src,
                "for2020_source_label": src_label,
                "theme": theme,
                "proxy_code": proxy_code,
                "proxy_label": proxy_label,
                "proxy_level": proxy_level,
                "confidence": round(score, 3),
            }
        )

    rows = []
    below_floor = []
    theme_results: dict[str, tuple[str, str, str, float]] = {}
    for theme, members in _THEME_BUCKETS.items():
        merged_text = " ".join(source_texts.get(m, "") for m in members)

        if theme in _MANUAL_OVERRIDES:
            proxy_code, proxy_label, proxy_level, score = _MANUAL_OVERRIDES[theme]
        else:
            group_scored = sorted(
                ((c, _group_score(theme, merged_text, c, group_label[c], group_texts.get(c, ""))) for c in candidate_groups),
                key=lambda t: t[1], reverse=True,
            )
            division_scored = sorted(
                ((d, _group_score(theme, merged_text, d, division_label[d], division_texts.get(d, ""))) for d in candidate_divisions),
                key=lambda t: t[1], reverse=True,
            )
            best_group, best_group_score = group_scored[0]
            best_division, best_division_score = division_scored[0]

            if best_group_score >= best_division_score + GROUP_PREFERENCE_MARGIN:
                proxy_code, proxy_label, proxy_level, score = best_group, group_label[best_group], "group", best_group_score
            else:
                proxy_code, proxy_label, proxy_level, score = best_division, division_label[best_division], "division", best_division_score

        if score < CONFIDENCE_FLOOR:
            below_floor.append((theme, members, proxy_code, proxy_label, round(score, 3)))
            continue
        theme_results[theme] = (proxy_code, proxy_label, proxy_level, score)
        for src in members:
            add_row(src, group_label[src], theme, proxy_code, proxy_label, proxy_level, score)

    if below_floor:
        print(f"  [for2020_division45_to_proxy] {len(below_floor)} theme(s) below confidence "
              f"floor {CONFIDENCE_FLOOR}, all member groups left unmapped (still hard-fail):")
        for theme, members, code, label, score in below_floor:
            print(f"    {theme!r} ({', '.join(members)}): best candidate was {code} {label!r} ({score})")

    # Group 4519 ("Other Indigenous data, methodologies and global Indigenous studies") is
    # heterogeneous, not a 3-way theme bucket -- handled field-by-field, plus its own group
    # (and bare division 45 itself) default to the "culture, language and history" theme's
    # own proxy as the broadest reasonable landing spot within division 45. That theme
    # resolves to OAX field "Arts and Humanities" -- the same target the user independently
    # confirmed as division 45's own sensible default.
    if "culture, language and history" in theme_results:
        default_code, default_label, default_level, default_score = theme_results["culture, language and history"]
        add_row("45", "INDIGENOUS STUDIES", "division-45 default (no group-level input)", default_code, default_label, default_level, default_score)
        add_row("4519", group_label["4519"], "division-45 default (heterogeneous group)", default_code, default_label, default_level, default_score)

    for field_code, theme in _4519_FIELD_TO_THEME.items():
        if theme in theme_results:
            proxy_code, proxy_label, proxy_level, score = theme_results[theme]
            field_label = for_df.loc[for_df["code"] == field_code, "label"].iloc[0]
            add_row(field_code, field_label, f"4519 field, reuses {theme!r} theme", proxy_code, proxy_label, proxy_level, score)

    # 451906 "Indigenous data and data technologies" and 451907 "Indigenous methodologies"
    # -- an initial algorithmic attempt at 451906 alone found division 46 (Information and
    # Computing Sciences, a decisive score), but 451907's score was degenerate (a single
    # generic word tying at 1.0 against many unrelated groups: Bioinformatics, Architecture,
    # Marketing...). User-provided override for both: FOR2020 group 4499 "Other human
    # society" (division 44's own NEC catch-all, already resolving cleanly to OAX "Social
    # Sciences"/Leiden "Social sciences and humanities") -- data governance/sovereignty and
    # research methodology are both fundamentally about how a society organises knowledge
    # and research, not primarily computing-technology or sociology-methods topics
    # specifically, so the broader human-society catch-all is the better single proxy for
    # both than either of the narrower individual picks.
    for field_code, field_label in [
        ("451906", "Indigenous data and data technologies"),
        ("451907", "Indigenous methodologies"),
    ]:
        add_row(field_code, field_label, "manual override (-> FOR2020 4499 Other human society)", "4499", group_label["4499"], "group", 0.7)

    # Group 4599 ("Other Indigenous studies") -- the last remaining gap. No sub-structure,
    # no prefix/gloss pattern, but user-confirmed: same proxy as 4519's own default, group
    # 4499 "Other human society" -- both are division 45's own generic "everything else"
    # catch-all, so they get the same generic non-Indigenous catch-all in return.
    add_row("4599", group_label["4599"], "manual override (-> FOR2020 4499 Other human society)", "4499", group_label["4499"], "group", 0.7)

    df = pd.DataFrame(rows)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(seed_path, index=False, encoding="utf-8")
    return df
