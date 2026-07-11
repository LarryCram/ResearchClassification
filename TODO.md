# Known gaps

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

## OAX/Leiden -> FOR2020 group-level (4-digit) precision: done, but partial coverage
`seeds/openalex_subfield_to_for_group.csv` (252 rows, algorithmic -- see its own docstring
for the scoring approach and the three failure modes found and fixed while building it)
plus the four `for2020_group_*.csv` tables now give group-level (4-digit) precision when
available. Coverage is ~60-80% of FOR's 213 groups depending on target (`for_group`
exploding is deliberately primary-only, trading lower coverage for not duplicating a
subfield's full count across several close-scoring alternate groups -- see
`explode_for_groups()`'s docstring). `resolve()` falls back to division-level automatically
for uncovered groups, so this degrades gracefully rather than failing.
