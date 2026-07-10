# Known gaps

## OAX <-> FOR2020 rebuild: abandoned mid-session, uncommitted, needs a different approach

Attempted a full rebuild of every OAX<->FOR2020 correspondence table (`seeds/openalex_field_to_for_division.csv`,
`seeds/openalex_subfield_to_for_group.csv`, a new `seeds/openalex_field_to_for_group.csv`, and the four
`for2020_*_openalex_*.csv` tables), after finding the original hand-typed OAX->FOR2020 seed and the
"empirical" FOR2020->OAX tables were not actually independent of each other (the latter routed through the
former via `build_leiden.py`'s `explode_for_divisions()`). **None of this is committed.** `git status` shows
modified/untracked files across `research_classification/` and `seeds/`; `build.py` was never run end-to-end
against the changes; the bundled `.duckdb` does not reflect any of this.

**New module**: `research_classification/cascade_match.py` -- a shared lexical matcher meant to replace ad hoc
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

**Reviewed and approved by the user directly:**
- `seeds/openalex_field_to_for_division.csv` (26 OAX fields -> FOR2020 divisions).
- `seeds/openalex_subfield_to_for_group.csv` (252 OAX subfields -> FOR2020 groups), 44 manual overrides
  applied after a full by-eye scan of every row.

**Unfinished, unreviewed, or actively broken:**
- `curate_openalex_field_to_for_precise.py` (group-level precision for OAX field input) -- built and ran,
  spot-checked by the assistant only, never reviewed by the user.
- `curate_for2020_to_openalex.py` (the FOR2020->OAX reverse direction) -- iterated on heavily, never
  converged. Real bugs found along the way: `topic_rank_resolve()` had no exact-match step at all (missed
  e.g. FOR2020 group "Architecture" == OAX subfield "Architecture"); the same "biggest bag wins" bias that
  affected earlier tables recurred here too (e.g. "PHYSICAL SCIENCES" landed on OAX field "Engineering"
  instead of "Physics and Astronomy"); OpenAlex has several genuinely duplicate-named subfields under two
  different parent fields (Genetics, Physiology, Microbiology, Neurology, Pharmacology, Archeology,
  Biochemistry) that silently blocked exact-match until a same-side self-test caught it. The last code
  change (a duplicate-label tie-break + contains-match tier added to `_exact_match`) was rejected by the
  user as still not making sense, and the session ended there without re-running or re-verifying it.
- `curate_openalex_to_leiden.py` (OAX -> Leiden main field, pure OAX-side) -- not started.
- `build_leiden.py`'s composition rewrite (FOR2020->Leiden via FOR2020->OAX x OAX->Leiden, replacing today's
  independent re-aggregation) -- not started.
- `curate_for2020_division45_to_proxy.py`'s import of shared text builders from `cascade_match.py` -- not
  started.
- `resolver.py` / `build.py` wiring to any of the new/rebuilt tables -- not started.
- Test suite -- not run since these changes began; expect many hardcoded-expectation failures.
- The `for2020_*_openalex_*.csv` tables (division/group -> OAX domain/field/subfield) never got a full user
  review -- the session ended mid-review, with the user auditing exact/contains-match coverage through a long
  series of ad hoc queries (single-word FOR/OAX label cross-checks, same-side self-match tests) rather than
  reviewing the generated tables directly.

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

**Recommendation for whoever picks this up:** don't resume by adding more matching-formula tiers. The user's
own diagnosis -- run a simple/cheap fuzzy pass, then have a human or LLM directly review and correct the
output rather than trying to make automated scoring converge on every case -- is worth taking at face value.
`cascade_match.py`'s exact-match and contains-match tiers (steps 1-1.5) are solid and were validated by direct
review; the raw bag-overlap fallback (step 2) and `topic_rank_resolve()` are the parts that kept needing
rescue-by-hand and are the better candidates to replace with a review-and-correct workflow rather than
further tuning.

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
