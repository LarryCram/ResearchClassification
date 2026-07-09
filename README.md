# research-classification

Harmonized research classification lookup: ANZSRC FOR/SEO (2020, 2008, and pre-2000
FOR1998/SEO1998), OpenAlex's topic hierarchy, Scopus ASJC, and the CWTS Leiden Ranking
Main Fields.

## Install

```
pip install git+https://github.com/LarryCram/ResearchClassification.git
```

That's it -- no separate build step, no data file to copy around. The package bundles its
own data (`research_classification/data/*.csv`, a few MB of small tables) and loads them
into an in-memory DuckDB on first use.

## Use

```python
from research_classification import Resolver

r = Resolver()

r.resolve("230104", "FOR1998", "FOR2020")   # pre-2000 code -> current FOR2020 equivalent
r.resolve("010101", "FOR2008", "FOR2020")   # FOR2008 code -> FOR2020
r.resolve("Chemistry", "OAX", "OAX_FIELD")  # label, current scheme

r.resolve("230104", "FOR1998", "OAX_FIELD")  # pre-2000 code -> OpenAlex field
r.resolve("230104", "FOR1998", "LEIDEN")     # pre-2000 code -> Leiden Main Field
```

Both `from_scheme` and `to_scheme` are always required, spelled out as one of these named
values -- never inferred, never guessed:

- **`from_scheme`**: `OAX`, `FOR1998`, `FOR2008`, `FOR2020`, `SEO1998`, `SEO2008`, `SEO2020`
- **`to_scheme`**: `OAX_DOMAIN`, `OAX_FIELD`, `OAX_SUBFIELD`, `OAX_TOPIC`, `FOR2020`, `SEO2020`, `LEIDEN`

Two rules hold everywhere:

- **Forward in time only.** Resolving moves toward FOR2020/SEO2020, never back to an older
  vintage (there's no way to ask this tool to go FOR2020 -> FOR2008 -> FOR1998).
- **Up the hierarchy only, never down.** A FOR/SEO input can reach `OAX_FIELD`/`OAX_SUBFIELD`
  and `LEIDEN`, but never `OAX_TOPIC` -- OpenAlex's 4,516 topics are far finer than anything
  honestly derivable from a coarser input, so that combination always raises `ValueError`
  rather than fabricating a guess. The same applies within OAX itself: `OAX_FIELD ->
  OAX_TOPIC` raises (one field has many topics), while `OAX_TOPIC -> OAX_FIELD` (walking up
  the real hierarchy) works and is exact.
- `SEO*` schemes can only ever target `SEO2020` -- SEO is an objective classification with
  no relationship to OAX/Leiden by design, so any other `to_scheme` raises immediately.

If a mapping genuinely doesn't exist (e.g. ANZSRC's Indigenous Studies division has no
counterpart anywhere in OpenAlex/ASJC's international taxonomy), `resolve()` raises
`LookupError` with an explanatory message rather than guessing. See `TODO.md` for this and
one other known, deliberately-deferred gap.

### Why both ends are always named explicitly

ANZSRC reused overlapping code ranges across revisions: `300101` means "Soil Physics" under
FOR1998 but "Agricultural biotechnology diagnostics" under FOR2020 -- two unrelated meanings,
same digit string (48% of FOR1998's 898 codes collide with a differently-meaning FOR2020
code this way). Naming `from_scheme` explicitly resolves this by construction -- there's no
ambiguity to guess at:

```python
r.resolve("300101", "FOR1998", "FOR2020")  # -> "Soil physics" (410605)
r.resolve("300101", "FOR2020", "FOR2020")  # -> "Agricultural biotechnology diagnostics"
```

### Leading zeros

FOR2008 codes in divisions 01-09 (556 of them) commonly lose their leading zero when read
through pandas/JSON/Excel, since those tools tend to infer an int type and drop it (e.g.
`"010101"` becomes `10101`). Since FOR/SEO codes are always exactly 2, 4, or 6 digits, an
observed length of 1, 3, or 5 is unambiguous, so `resolve()` recovers it automatically --
pass either `10101` or `"010101"`, same result. `int` values are accepted directly.

See `examples/map_category_to_leiden.py` for a fuller worked example, including handling
free-text category columns that don't match any code/label exactly (the one place this
project still needs a fuzzy-match step, since `resolve()` itself only ever does exact
lookups).

## Rebuilding the data

Only needed if you're changing the source classification files themselves
(`data_untracked/`, not tracked in this repo). Requires the `build` extra:

```
pip install -e ".[build]"
python build.py          # regenerates research_classification/data/*.csv
python tests/test_resolver.py
```
