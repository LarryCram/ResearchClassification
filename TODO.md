# Known gaps

## FOR2020 Division 45 (Indigenous Studies) has no OAX/Leiden equivalent at any granularity
Permanent, not a bug: no counterpart exists anywhere in OpenAlex/ASJC's international
taxonomy, at the field, subfield, or (now) group level. `resolve()` reports this explicitly
(a `LookupError` with an explanatory note) rather than guessing.

Confirmed directly when the group-level tables were added: all 20 of division 45's own FOR
groups (4501-4599) are the *only* groups with zero coverage in every one of the four
`for2020_group_*.csv` tables -- everything else in FOR2020 (193/213 groups) has at least
division-level coverage, and 129-172/213 have group-level coverage. This was worth checking
explicitly since going to finer granularity seemed like it might help, but it doesn't:
Division 45 has no path in from OpenAlex/ASJC at *any* level of precision, coarse or fine,
because none of OpenAlex's 26 top-level fields was ever curated to point there in the first
place (there's no Indigenous-studies-equivalent field to start from), and that absence
propagates all the way down regardless of how finely the rest of the taxonomy is resolved.

## OAX/Leiden -> FOR2020 group-level (4-digit) precision: done, but partial coverage
`seeds/openalex_subfield_to_for_group.csv` (252 rows, algorithmic -- see its own docstring
for the scoring approach and the three failure modes found and fixed while building it)
plus the four `for2020_group_*.csv` tables now give group-level (4-digit) precision when
available. Coverage is ~60-80% of FOR's 213 groups depending on target (`for_group`
exploding is deliberately primary-only, trading lower coverage for not duplicating a
subfield's full count across several close-scoring alternate groups -- see
`explode_for_groups()`'s docstring). `resolve()` falls back to division-level automatically
for uncovered groups, so this degrades gracefully rather than failing.
