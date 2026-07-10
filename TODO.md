# Known gaps

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

`resolve()` now reaches OAX/Leiden for **16 of division 45's 18 themed groups** (all except
4519/4599, see below) by routing through a proxy FOR2020 group or division representing the
same underlying concept, tagged `match_method="cultural_proxy"` in the result so it's always
visible as a designed heuristic hop, not official ANZSRC content -- confidence is the proxy
match's own score multiplied into whatever confidence the proxy target itself resolves with.
4 of the 6 themes (education, health and wellbeing, environmental knowledges, culture/
language/history) resolved via lexical scoring alone; 2 (sciences; peoples, society and
community) scored as pure noise algorithmically (best "sciences" candidates were things like
"Medical and biological physics" -- no coherent winner, since ANZSRC's own "sciences" and
"peoples, society and community" theme buckets are each multi-division in breadth) and were
resolved instead via direct user confirmation: sciences -> Environmental Sciences (division
41); peoples, society and community -> Human geography (group 4406).

**Genuinely unmapped, by design**: groups 4519 ("Other Indigenous data, methodologies and
global Indigenous studies") and 4599 ("Other Indigenous studies") have no prefix/gloss
pattern at all -- Indigenous data sovereignty, Indigenous research methodologies -- and no
non-Indigenous analogue exists to proxy through. `resolve()` still raises `LookupError` for
these two, with an explanatory note, rather than guessing.

## OAX/Leiden -> FOR2020 group-level (4-digit) precision: done, but partial coverage
`seeds/openalex_subfield_to_for_group.csv` (252 rows, algorithmic -- see its own docstring
for the scoring approach and the three failure modes found and fixed while building it)
plus the four `for2020_group_*.csv` tables now give group-level (4-digit) precision when
available. Coverage is ~60-80% of FOR's 213 groups depending on target (`for_group`
exploding is deliberately primary-only, trading lower coverage for not duplicating a
subfield's full count across several close-scoring alternate groups -- see
`explode_for_groups()`'s docstring). `resolve()` falls back to division-level automatically
for uncovered groups, so this degrades gracefully rather than failing.
