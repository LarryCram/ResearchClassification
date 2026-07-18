# Known gaps

## Bare-label vintage lookups resolving to a finer level than intended: FIXED

`resolve(value, from_scheme, to_scheme)` with a bare label (not a code) could silently
return a match at a finer classification level than the caller meant. Repro:
`resolve("Transport", "SEO1998", "SEO2020")` returned the unrelated objective-level leaf
`170104` ("Transport energy efficiency") instead of division `27` ("TRANSPORT") -- both
`bridge_seo1998_seo2020` rows (`source_code=69` "TRANSPORT" division, `source_code=660403`
"Transport" objective) are legitimately `is_primary=True` for their own, different
`source_code`, so `ORDER BY is_primary DESC` alone didn't break the tie between them;
whichever row the table scan returned first won arbitrarily.

Fixed in `_resolve_vintage_to_current()`'s bare-label query: added `LENGTH(source_code) ASC`
as a secondary sort key, so a label collision across granularities always resolves to the
coarsest match -- a bare-text query carries no code, so there's never a basis to prefer a
finer level over a coarser one sharing the same label. Applies to all four
`_VINTAGE_BRIDGE_TABLE` lookups via the shared code path. Scanned all four bridge tables for
the same collision class: real and widespread, not a one-off -- 26 in FOR1998
(e.g. "Automotive Engineering" group 2904 vs field 290401), 2 in FOR2008, 85 in SEO1998, 2 in
SEO2008. Regression test: `tests/test_resolver.py::test_bare_label_lookup_prefers_coarser_level`.

## OAX <-> FOR2020: RESOLVED, via a hand-curated mapping recovered from an earlier project

The prior approach (documented below, kept for history) tried to build the FOR2020->OAX
direction algorithmically -- lexical cascade scoring, then per-topic rank concentration --
and never converged, ending with the session abandoned mid-review.

That direction turned out to already be solved: `data_untracked/EARLIER_FOR_OAX_analysis/`
(an earlier, separate, less-structured project) contained a hand-curated dict mapping every
FOR2020 division to an OAX field and every FOR2020 group to an OAX subfield, with a
hierarchy-nesting constraint enforced at its own build time and inline human rationale on
every entry. Ported into `research_classification/curate_for2020_to_openalex.py`
(`FIELD_BY_DIVISION`, `SUBFIELD_BY_GROUP`), replacing both the never-converged cascade/
topic-rank approach *and* `build_leiden.py`'s old `explode_for_divisions()`/
`explode_for_groups()` generation of the `for2020_*_openalex_*.csv` tables (which was
circular: it derived a FOR node's "empirical" OAX distribution by routing back through
`bridge_openalex_for(_group).csv`, itself generated FROM the reverse OAX->FOR seed).

Reviewed this session via a falsification-driven pass (direct domain judgment, not just the
lexical/cross-direction signals, which produce both false positives -- e.g. "Chemical
Engineering" being both an OAX field and a FOR group name -- and false negatives -- e.g.
"equine"/"veterinary" sharing no lexical overlap despite being a clearly correct match).
Two real issues found and fixed:

- **Division 33 "Built Environment and Design"** was mapped to OAX field 12 (Arts and
  Humanities); OAX field 22 (Engineering) has exact-name subfields "Architecture" (2216) and
  "Building and Construction" (2215) that were unreachable as a result. Reassigned the
  division to field 22; groups 3303 (Design) and 3304 (Urban and regional planning) get their
  own cross-field overrides back toward Arts and Humanities / Social Sciences since neither
  fits Engineering.
- **15 individual groups** are a much better fit for a *different* OAX field than their
  division's own assignment (each division's field is right for every other group in it, so
  reassigning the whole division would just break those). Given explicit group-level
  overrides in `GROUP_FIELD_OVERRIDE`, tagged `match_method="manual_override"`:
  division 31's Biochemistry/Bioinformatics/Genetics/Industrial biotechnology/Microbiology (5
  groups, -> OAX fields 13/24), Dentistry (-> field 35), Nursing (-> field 29), Chemical/
  Environmental/Materials engineering (-> fields 15/23/25), Communication/Cultural studies
  (-> field 33), and Library and information studies (-> field 33's "Library and Information
  Sciences" subfield, found during review). Confirmed directly with the user that breaking
  the division-field/group-subfield nesting for these specific, individually-reviewed cases
  is fine -- it's inherent in the two tables and well known in the ASJC context.
- A handful of other borderline cases (5199 "Other physical sciences" -> Acoustics and
  Ultrasonics, 5103 Classical physics -> Statistical and Nonlinear Physics, 5108 Quantum
  physics -> Condensed Matter Physics, 3002 Agriculture/land/farm management -> Agronomy and
  Crop Science, 3602 Creative and professional writing -> Literature and Literary Theory,
  4604 Cybersecurity and privacy -> Computer Networks and Communications) were reviewed and
  left as-is: each is the best available fit given OAX's actual subfield inventory for the
  applicable field, not a correctable oversight.

Every row in `seeds/for2020_division_to_openalex_field.csv` (22 rows, division 45 excluded --
see its own cultural_proxy mechanism below) and `seeds/for2020_group_to_openalex_subfield.csv`
(193 rows) is marked `reviewed` with today's date. `resolver.py` now reports the real
provenance (`manual_curated` for direct ported facts, `manual_override` for the 16 cross-field
exceptions, `derived_empirical` only for the division-level subfield roll-up, which has no
direct curated fact and is instead a majority vote over the division's own now-independently-
curated groups) instead of a hardcoded string. Full exhaustive coverage (2,203/2,203 FOR2020
codes) holds, confirmed by `tests/test_resolver.py`.

Along the way, fixed three pre-existing bugs that were silently blocking `build.py` from ever
running to completion on `main` (confirmed against a clean checkout): a dead import
(`curate_for2020_division45_to_proxy.py` importing a since-renamed `_group_score`, now
deferred/lazy so it doesn't crash on module load when its seed already exists) and three
legitimate `match_method` values (`exact_match`, `contains_match`, `below_floor`, already
produced by `cascade_match.py`/`curate_openalex_subfield_to_for_group.py`) missing from
`hierarchy.py`'s `MATCH_METHODS` allow-list.

**Lock-in going forward:** `seeds/*.csv` are cache-guarded (present on disk = never
regenerated) -- this was already the convention, but `build_leiden.py` used to bypass it by
independently regenerating the same `for2020_*_openalex_*.csv` tables every run. That's fixed:
`build_leiden.py` no longer touches those tables at all (they come from
`curate_for2020_to_openalex.py` alone) and only composes `for2020_*_leiden_main_field.csv`
through the new curated seed. `build.py` also now warns loudly if a previously-built project
is missing a locked-in seed file, rather than silently regenerating it from scratch.

<details>
<summary>Prior (abandoned) approach, kept for history</summary>

Attempted a full rebuild of every OAX<->FOR2020 correspondence table (`seeds/openalex_field_to_for_division.csv`,
`seeds/openalex_subfield_to_for_group.csv`, a new `seeds/openalex_field_to_for_group.csv`, and the four
`for2020_*_openalex_*.csv` tables), after finding the original hand-typed OAX->FOR2020 seed and the
"empirical" FOR2020->OAX tables were not actually independent of each other (the latter routed through the
former via `build_leiden.py`'s `explode_for_divisions()`).

**`research_classification/cascade_match.py`**: a shared lexical matcher meant to replace ad hoc
per-script matching, built up over many iterations across one long session:
1. Exact word-set match (`exact_match_words()`), with a small AU/UK<->US spelling dictionary and a minimal
   stopword list (only genuine grammatical connectors, not domain words like "science"/"other").
2. Contains-match (`contains_match()`, added last) -- one label's word set a unique proper subset of the
   other's, e.g. "Zoology" vs "Animal Science and Zoology".
3. Raw word/stem SET-INTERSECTION SIZE (`bag_overlap()`) as a last-resort fallback -- deliberately not a
   ratio (Jaccard/overlap-coefficient); several ratio-based formulas were each found, in turn, to
   systematically favor whichever candidate had the smaller (or, for Jaccard, the larger) bag.
4. `topic_rank_resolve()` for the FOR2020->OAX direction -- scores individual OpenAlex topics against a
   FOR2020 node's bag and looks at where the top N concentrate.

Reviewed and approved by the user directly (still current, untouched by the above):
`seeds/openalex_field_to_for_division.csv` (26 OAX fields -> FOR2020 divisions) and
`seeds/openalex_subfield_to_for_group.csv` (252 OAX subfields -> FOR2020 groups, 44 manual
overrides applied after a full by-eye scan of every row).

**The user's assessment, in the order given:**
- Repeatedly corrected the scoring formula across the session (Jaccard -> overlap coefficient -> raw count ->
  stemming -> minimal stopwords -> contains-match), each time after finding concrete wrong outputs --
  described this as "going around in circles."
- Proposed a different overall strategy instead of continuing to refine matching formulas: "fuzzy matching
  followed by an LLM subscription to find anomalies then a scheme to work on them," attributing the
  difficulty to "the simplicity arising from the narrow linguistic aspects of this 'research language'
  problem" -- i.e., judged that direct LLM review and correction of the output would be faster and more
  reliable than continuing to build automated scoring/matching logic.
- Ran a long, careful manual audit (single-word label cross-checks between OAX and FOR2020, then a same-side
  self-match test) that did surface real, concrete bugs (the Paediatrics/Clinical-sciences bag-size bias; the
  missing exact-match step in the FOR2020->OAX direction; the OAX duplicate-subfield-name issue) -- the
  underlying diagnosis (formula-only fixes were not converging) is backed by real evidence, not just
  frustration.
- Final message, after the last fix (duplicate-name tie-break + contains-match added to the FOR2020->OAX
  direction): "That make no sense after you do it nor did it make any sense before. I have had it" -- asked
  to close the session and hand off to a different coding assistant.

This diagnosis is exactly what got followed through on above: no more matching-formula tiers --
a cheap ported mapping, then direct LLM review and correction of the actual output.
</details>

## SEO -> SDG: done for SEO only; FOR/OAX -> SDG deferred
`resolve()` reaches `SDG_GOAL`/`SDG_PILLAR` from every SEO vintage (SEO1998/2008/2020), via
`research_classification/curate_seo_to_sdg.py` -- a user-provided, single-valued
division-level alignment table, plus the UN's own 5-pillar grouping above the 17 goals
(`research_classification/build_sdg.py`). The user's source table's own division numbering
didn't match ours for 6 of 19 divisions (looked like a different/draft SEO2020 revision --
our real division 27 is "Transport", 28 is "Expanding Knowledge"; the source table had
"Transport" at 31 and no counterpart for "Expanding Knowledge" at all). Resolved by matching
on label rather than the source's code, plus two direct user overrides (division 27 reuses
the source's own "Transport" row; division 28 -> SDG 9). Full 19/19 coverage, exhaustively
tested (`test_exhaustive_seo2020_to_sdg_coverage`).

**Deferred, explicitly out of scope for now**: the user's next ask is "a higher aggregation
like Leiden for FOR" -- i.e. FOR (and/or OAX) reaching SDG too. `to_scheme="SDG_GOAL"`/
`"SDG_PILLAR"` currently raise `ValueError` for any `from_scheme` other than SEO*, on
purpose -- not a gap to close incidentally, a separate future request.

## FOR2020 Division 45 (Indigenous Studies) -> OAX/Leiden: resolved via cultural proxy
Division 45 has no *direct* OpenAlex/ASJC counterpart at any granularity (confirmed: none
of OpenAlex's 26 top-level fields was ever curated to point there, so the absence propagates
through every derived table regardless of precision). But division 45's own content is,
almost entirely, the same research concept as elsewhere in FOR2020 re-scoped to an
Aboriginal & Torres Strait Islander / Maori / Pacific Peoples population -- its group and
field labels say so directly ("Aboriginal and Torres Strait Islander " + concept, "Pacific
Peoples " + concept, or a Maori-language label with the English gloss in parens). See
`research_classification/curate_for2020_division45_to_proxy.py` (full rationale and the two
concrete failure modes found and fixed while building it, matching this pipeline's existing
pattern of iterating a lexical scorer against spot-checked real output).

`resolve()` now reaches OAX/Leiden for **all 2,203 of FOR2020's codes** (confirmed
exhaustively -- `test_exhaustive_for2020_to_oax_leiden_coverage` resolves every single one),
by routing division-45 codes through a proxy FOR2020 group or division representing the same
underlying concept, tagged `match_method="cultural_proxy"` so it's always visible as a
designed heuristic hop, not official ANZSRC content -- confidence is the proxy match's own
score multiplied into whatever confidence the proxy target itself resolves with.

- 4 of the 6 themes (education, health and wellbeing, environmental knowledges, culture/
  language/history) resolved via lexical scoring alone across all 18 themed groups
  (4501-4518). 2 (sciences; peoples, society and community) scored as pure noise
  algorithmically (best "sciences" candidates were things like "Medical and biological
  physics" -- no coherent winner, since both theme buckets are each multi-division in
  breadth) and were resolved instead via direct user confirmation: sciences -> Environmental
  Sciences (division 41); peoples, society and community -> Human geography (group 4406).
- Group **4519** ("Other Indigenous data, methodologies and global Indigenous studies") is
  heterogeneous, not a themed sibling -- 5 of its 8 fields are literally "Global Indigenous
  studies " + one of the 6 theme names and reuse that theme's proxy directly. Its other two
  fields, 451906 ("...data and data technologies") and 451907 ("...methodologies"), were
  resolved via direct user confirmation to FOR2020 group 4499 ("Other human society",
  division 44's own NEC catch-all, already resolving cleanly to OAX "Social Sciences") rather
  than either field's individually-scored pick (division 46 for 451906; a degenerate,
  meaningless score for 451907 -- a single generic word tying at 1.0 against unrelated groups
  like Bioinformatics and Architecture) -- data governance and research methodology are both
  fundamentally about how a society organises knowledge, not computing-technology or
  sociology-methods specifically. Bare division 45 itself, and 4519's own catch-all/NEC
  field, both default to the "culture, language and history" theme's proxy (OAX field "Arts
  and Humanities") -- confirmed directly by the user as division 45's sensible general
  landing spot.

Group **4599** ("Other Indigenous studies") and its sole field 459999 -- no sub-structure,
no algorithmic signal at all -- were the last remaining gap; user-confirmed to the same
proxy as 4519's own default, FOR2020 group 4499 "Other human society".

## FOR1998/FOR2008 -> FOR2020 at division (2-digit) and group (4-digit) level: RESOLVED

`resolve()` used to only reach FOR2020 from FOR1998/FOR2008 at field level (6-digit) --
neither vintage's official ABS correspondence source publishes anything coarser than field
level (confirmed directly: the 2008->2020 sheet's 2443 real rows are all 6 digits, none at 2
or 4; same for the 1998->2008 "Table 1" source). Closed via
`research_classification/build_correspondences_rollup.py`: division/group bridge rows are
derived by rolling up the existing field-level bridge tables (majority vote per
division/group prefix -- same pattern as OAX/Leiden's `_DIVISION_CENTRIC`/`_GROUP_CENTRIC`
roll-ups), tagged `match_method="derived_empirical"`. `_NATIVE_LENGTHS["FOR2008"]` widened
from `{6}` to `{2, 4, 6}` (its own codes are natively 2/4/6-digit); FOR1998 got dedicated
handling in `_normalize_code()` instead, since its codes are a flat 6-digit space with
right-padding (division `210000`, discipline `230100`) -- it strips that padding to the
genuine short code (`"21"`, `"2301"`) that the bridge table is now keyed on for those levels,
while still accepting the zero-padded 6-digit form too.

Confirmed via `examples/map_category.py`, which runs every FOR1998/FOR2008 division/group/
field code from `data_untracked/12970_1998_2008.xlsx` through `resolve()`:

- **FOR2008: 100% at every level** -- 22/22 division, 157/157 group, 1241/1241 field. The
  last 3 field-level gaps (`119901` Podiatry, `119902` Medical Biotechnology, `119903`
  Therapies and Therapeutic Technology -- none has an official ABS correspondence or a clean
  label match) were closed with user-provided hand-coded overrides
  (`MANUAL_FIELD_OVERRIDES` in `build_correspondences_rollup.py`), resolving to their best-fit
  FOR2020 *group* directly (`4201` Allied health and rehabilitation science; `3206` Medical
  biotechnology) since no FOR2020 field fits either -- a deliberate level-coarsening, tagged
  `match_method="user_provided"`.
- **FOR1998: group and field 100%** (138/138 group; 895/895 field -- the last 2 field-level
  gaps, `360205` Social Policy and `360206` Defence Policy, had no FOR2020 field of their own
  under discipline 3602's own FOR2020 group target, and were closed the same way as FOR2008's
  three: user-provided hand-coded overrides to their parent discipline's FOR2020 group, `4407`
  Policy and administration), **division 22/24** -- the 2 failures are FOR1998 divisions
  `21` "SCIENCE-GENERAL" and `22` "SOCIAL SCIENCES, HUMANITIES AND ARTS-GENERAL". Confirmed
  genuinely unresolvable, not a gap to close: checked all 23 FOR2020 divisions, none is a
  general/multidisciplinary catch-all, and both 1998 divisions have zero child disciplines/
  subjects of their own in the source data to derive a target from either way. Per-user
  decision: leave these as a documented, permanent absence rather than force a bad match --
  `resolve()` special-cases `("FOR1998", "21")`/`("FOR1998", "22")` via `_KNOWN_UNRESOLVABLE`,
  emits an informative `UserWarning` explaining why, and returns `None` instead of raising, so
  a caller iterating many codes doesn't need a try/except for a known, permanent case.

`build_correspondences_rollup.py`'s `run()` is idempotent (filters to `canonical_level ==
"field"` before recomputing roll-ups), safe to re-run after either bridge CSV already has
division/group rows written into it from a prior run.

Still separately true: a non-ABS-official 4-digit group-level FOR2008->FOR2020 table sits
unused in `data_untracked/2008_FoR_to_2020_FoR_conversion_04Apr2022.xlsx` (180 rows, near
1:1) -- not needed now that the roll-up approach gives 100% FOR2008 group coverage, but
worth a cross-check against it if the roll-up's group-level confidence ever looks suspicious
for a specific code.

## OAX/Leiden -> FOR2020 group-level (4-digit) precision: done, full coverage
`seeds/openalex_subfield_to_for_group.csv` (252 rows, algorithmic -- see its own docstring
for the scoring approach and the three failure modes found and fixed while building it)
plus the four `for2020_group_*.csv` tables now give group-level (4-digit) precision when
available. Coverage is ~60-80% of FOR's 213 groups depending on target (`for_group`
exploding is deliberately primary-only, trading lower coverage for not duplicating a
subfield's full count across several close-scoring alternate groups -- see
`explode_for_groups()`'s docstring). `resolve()` falls back to division-level automatically
for uncovered groups, so this degrades gracefully rather than failing.

The OAX subfield -> FOR2020 group direction itself (`bridge_openalex_for_group.csv`) is now
**fully audited, not just algorithmic**: of the 252 subfields, 46 were originally
`below_floor` (no confident lexical match at all) and the remaining 206 had a median
confidence of only ~0.22, meaning many of the "confident" picks were likely wrong too, not
just the unmatched ones. Rather than another round of formula-tuning (same lesson as the
FOR2020->OAX direction below), every one of the 252 was reviewed directly against its own
candidate pool (`research_classification/audit_oax_for_bridges.py`, a standalone diagnostic
dump tool kept committed for future re-audits) and corrected via `_MANUAL_OVERRIDES` where
the lexical pick was wrong -- 47 new entries, on top of the ~44 already there from an earlier
session. Result: **0 `below_floor` primaries left, all 252/252 subfields resolve to a real,
confident FOR2020 group** (`test_exhaustive_oax_subfield_to_for2020_group_coverage` is the
permanent regression guard). None of the corrections were ambiguous enough to need surfacing
to the user for a manual tie-break (the plan's own `<20`-case bar was met with room to spare
-- the reviewed-and-decided count converged to 0 genuinely unresolvable cases). The 26-row
OAX field -> FOR2020 division bridge (`bridge_openalex_for.csv`) got the same treatment on a
smaller scale: 4 overrides (Economics/Econometrics/Finance -> the dedicated ECONOMICS
division it was missing entirely; Energy -> Engineering, correcting a `contains_match` false
positive on the bare word "energy" landing on physics' "Particle and high energy physics";
Decision Sciences -> Commerce/Management per user direction; Health Professions -> Health
Sciences, already fixed in an earlier session).

## OAX topic -> FOR2020 field (6-digit leaf) precision: new, "cluster down" within each matched group
The finest level on both sides now reaches each other too. Once a subfield is confidently
pinned to a FOR2020 group (see above), `curate_openalex_topic_to_for_field.py` constrains
each of that subfield's own OAX topics to *only* the FOR2020 fields inside that matched group
(avg ~9.2 candidates, min 1, max 32 -- never the full 1,967-field space) and matches
individually, using the topic's label + `keywords` + `summary` (sourced from the raw
`OpenAlex_topic_mapping_table.xlsx`, now tracked directly in `research_classification/data/`
rather than depending on the gitignored `data_untracked/` copy -- see
`build_openalex.py`'s `SRC`) against the FOR2020 field's label (the only text available at
that level -- no field-level definitions exist anywhere in the source data). Groups with
exactly one field are trivial (direct assignment, no scoring needed).

Result: 3,918/4,516 topics (87%) reach real field-level precision; the remaining 598 don't
clear the lexical floor and are recorded as `below_floor` in `bridge_openalex_for_topic.csv`
rather than forced to a guess. Per explicit user direction, there is **no `<20`-case manual
review bar at this scale** (unlike the subfield->group audit above) -- LLM-only judgment was
accepted, with two spot-checked overrides added after a targeted sample review: "Rheumatoid
Arthritis Research and Therapies" (an exact-name field, "Rheumatology and arthritis", existed
in the same matched group but was missed because "rheumatoid"/"rheumatology" don't share a
tokenized root) and "Diabetes and associated disorders" (user-directed to "Epigenetics" within
its own matched Genetics group, rather than crossing out to a different group's
"Endocrinology" field -- the same OpenAlex topic ID can genuinely represent the genetics/
epigenetics angle on diabetes specifically, distinct from other diabetes-related topics that
may sit under a clinical/endocrine subfield instead).

`resolve()`'s `_resolve_oax_to_for2020()` was restructured around an explicit ordered tier
list (`_OAX_TO_FOR2020_TIERS`: topic->field, subfield->group, field->division), trying the
finest tier the input supports and cascading to the next-coarsest whenever a tier's own
primary is `below_floor` -- so a below_floor topic-level guess is never surfaced directly by
`resolve()` (it gracefully degrades to that topic's subfield's group-level answer instead),
even though it's still visible in `bridge_openalex_for_topic.csv` for anyone inspecting the
raw data. This restructuring also fixed two real, pre-existing bugs found while doing it: the
old two-tier logic hardcoded the literal strings `"constrained_lexical"`/`"manual_curated"`
as `match_method` regardless of the row's real value, and its group-tier fallback check
(`if row: ...`) never actually triggered for `below_floor` rows (every subfield already had
an `is_primary=True` row, `below_floor` or not) -- both fixed as part of the same change, not
separately (`test_oax_for2020_match_method_not_hardcoded` is the regression guard).

Division 45 (Indigenous Studies) has no interaction with any of this: it's already excluded
from the OAX->FOR2020 candidate pool at the group level (`curate_openalex_subfield_to_for_group.py`
filters it out before scoring), and since the topic tier's candidate pools are always subsets
of an already-matched non-45 group's own fields, division 45 fields can never surface as a
topic-level target either -- no code needed to special-case it further. The existing
`cultural_proxy` mechanism (`curate_for2020_division45_to_proxy.py`) remains exclusively part
of the *other* direction (FOR2020->OAX) and is untouched by any of this.

Known, accepted, non-blocking gap: `bridge_openalex_for.csv` also feeds `build_leiden.py`'s
`bridge_leiden_for.csv` (an OAX-field-to-FOR2020-division majority vote for Leiden), which is
now one commit stale relative to this audit's 4 field-level overrides -- not fixed in this
pass since regenerating it needs `data_untracked/classification_openalex_2023nov/*.tsv`
(absent in this checkout), and it's low-risk regardless since `LEIDEN` isn't currently a
valid `from_scheme` for `resolve()`, so `bridge_leiden_for.csv` is presently unreachable from
the public API either way.
