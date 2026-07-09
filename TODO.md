# Known gaps

## FOR2020 Division 45 (Indigenous Studies) has no OAX/Leiden equivalent
Permanent, not a bug: no counterpart exists anywhere in OpenAlex/ASJC's international
taxonomy. `resolve()` reports this explicitly (`method="unavailable"`, with a note) rather
than guessing. See `resolver.py`'s docstrings.

## OAX/Leiden -> FOR2020 is capped at division (2-digit) level
The only curated seed linking OAX to FOR (`seeds/openalex_field_to_for_division.csv`) maps
26 OpenAlex fields to 23 FOR divisions -- that's the finest FOR granularity honestly
derivable when the input is OAX or Leiden. Getting FOR2020 *group* (4-digit) output from an
OAX/Leiden input would require new curation at that finer granularity (e.g. mapping
OpenAlex's 252 subfields onto FOR's 213 groups), not a mechanical extension of what's
already built. Deferred until there's a concrete need -- flag if this becomes a blocker.
