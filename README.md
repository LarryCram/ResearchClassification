# research-classification

Harmonized research classification lookup: ANZSRC FOR/SEO (2020, 2008, and pre-2000
FOR1998/SEO1998), OpenAlex's topic hierarchy, Scopus ASJC, and the CWTS Leiden Ranking
Main Fields.

## Install

```
pip install git+https://github.com/LarryCram/ResearchClassification.git
```

That's it -- no separate build step, no data file to copy around.

### How the bundled data loads

`Resolver()` opens a pre-built `research_classification.duckdb` (bundled in
`research_classification/data/`) directly, read-only. Measured on this repo's own data
(~21K rows across 28 tables): **~10ms** to open the `.duckdb` file directly, versus **~360ms**
to rebuild an equivalent in-memory database from the source CSVs on every call -- a 36x
difference, and large enough to matter if `Resolver()` gets instantiated repeatedly (a shell
loop invoking a script many times, a notebook restarted often, tests that each create a
fresh instance), not just once per process.

The source CSVs (`research_classification/data/*.csv`) are bundled too, both as a
git-diffable audit trail (`.duckdb` binary diffs are opaque; the CSVs are what `build.py`
actually rebuilds from and what shows up cleanly in `git log`) and as an automatic fallback:
DuckDB's on-disk storage format isn't guaranteed compatible indefinitely across `duckdb`
library versions, so a `.duckdb` file built with one version can in principle fail to open
under a much older or newer one. Since this package is meant to be `pip install`-ed
unmodified into new projects over a period of years -- exactly the scenario where dependency
versions drift outside this repo's control -- `Resolver()` catches that failure, transparently
rebuilds an in-memory database from the bundled CSVs instead (slower, but unaffected by the
version mismatch), and raises a `RuntimeWarning` so it's visible rather than silent:

```python
import warnings
with warnings.catch_warnings(record=True) as caught:
    r = Resolver()
    if caught:
        print("fell back to CSV rebuild:", caught[0].message)
```

If you ever see that warning, rebuild the bundled `.duckdb` file with whatever `duckdb`
version is currently installed (`python build.py`, or just
`research_classification.build_duckdb.run()`) and commit the result.

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

### What `resolve()` returns

A frozen `CanonicalResult` dataclass:

```python
CanonicalResult(
    input_value="230104",        # exactly what you passed in (post leading-zero recovery)
    from_scheme="FOR1998",       # echoes the from_scheme argument
    to_scheme="OAX_FIELD",       # echoes the to_scheme argument
    code="26",                   # the resolved code, in to_scheme's own code space
    label="Mathematics",         # the resolved code's official/canonical label
    level="field",               # to_scheme's own granularity: e.g. division/group/field
                                  # (FOR/SEO), domain/field/subfield/topic (OAX), main_field (LEIDEN)
    match_method="derived_empirical",  # HOW this result was produced -- see below
    confidence=1.0,              # 0.0-1.0, meaning depends on match_method -- see below
    alternates=(),               # other candidate CanonicalResults, when more than one
                                  # existed (e.g. a many-to-many ABS correspondence) --
                                  # empty unless there was a real judgment call to make
)
```

`confidence` is never a vague "how sure am I" number -- what it means is determined by
`match_method`, which is always one of:

| `match_method` | meaning | typical `confidence` |
|---|---|---|
| `identity` | input already *is* a `to_scheme` code/label, no resolution needed | always `1.0` |
| `explicit_official` | a direct ABS/ANZSRC-published correspondence table row | always `1.0` |
| `explicit_official_transitive` | chained through an intermediate official table (e.g. FOR1998->FOR2008->FOR2020) | `0.9` or the chain's own weakest link |
| `exact_key_join` | codes are numerically identical across schemes (ASJC/OpenAlex) | always `1.0` |
| `derived_empirical` | majority-vote statistic over real joined data (e.g. Leiden main field <-> FOR division) | the vote share, e.g. `0.95` |
| `manual_curated` | the one hand-curated seed (OpenAlex field -> FOR division), scored by keyword overlap against ABS's own definitions | the overlap score |
| `constrained_lexical` | algorithmic lexical match within a hierarchically-constrained candidate pool | the lexical score |
| `lexical` | ABS's own "p"-flagged many-to-many ties, broken by string similarity | the similarity score |
| `cultural_proxy` | routed through a non-Indigenous FOR2020 proxy for division 45 (Indigenous Studies) -- see below | the proxy match's score, possibly compounded with the proxy target's own confidence |
| `user_provided` | externally-sourced content the user supplied and confirmed directly (SEO -> SDG) -- no computed score, confidence assigned directly | as assigned; `1.0` throughout for SEO->SDG |

Both `from_scheme` and `to_scheme` are always required, spelled out as one of these named
values -- never inferred, never guessed:

- **`from_scheme`**: `OAX`, `FOR1998`, `FOR2008`, `FOR2020`, `SEO1998`, `SEO2008`, `SEO2020`
- **`to_scheme`**: `OAX_DOMAIN`, `OAX_FIELD`, `OAX_SUBFIELD`, `OAX_TOPIC`, `FOR2020`, `SEO2020`,
  `LEIDEN`, `SDG_GOAL`, `SDG_PILLAR`

Two rules hold everywhere:

- **Forward in time only.** Resolving moves toward FOR2020/SEO2020, never back to an older
  vintage (there's no way to ask this tool to go FOR2020 -> FOR2008 -> FOR1998).
- **Up the hierarchy only, never down.** A FOR/SEO input can reach `OAX_FIELD`/`OAX_SUBFIELD`
  and `LEIDEN`, but never `OAX_TOPIC` -- OpenAlex's 4,516 topics are far finer than anything
  honestly derivable from a coarser input, so that combination always raises `ValueError`
  rather than fabricating a guess. The same applies within OAX itself: `OAX_FIELD ->
  OAX_TOPIC` raises (one field has many topics), while `OAX_TOPIC -> OAX_FIELD` (walking up
  the real hierarchy) works and is exact.
- `SEO*` schemes can only ever target `SEO2020`, `SDG_GOAL`, or `SDG_PILLAR` -- SEO is an
  objective classification with no relationship to OAX/Leiden by design, so any other
  `to_scheme` raises immediately. `FOR*`/`OAX` cannot reach `SDG_GOAL`/`SDG_PILLAR` yet
  (planned as a follow-on).

If a mapping genuinely doesn't exist, `resolve()` raises `LookupError` with an explanatory
message rather than guessing. See `TODO.md` for coverage caveats.

### SEO -> UN Sustainable Development Goals

Every SEO vintage resolves to the UN SDGs, via a user-provided division-level alignment
table (`research_classification/curate_seo_to_sdg.py`) -- single-valued (one SDG per
division) and, above that, the UN's own "5 Ps" pillar grouping (People, Planet, Prosperity,
Peace, Partnership):

```python
r.resolve("20", "SEO2020", "SDG_GOAL")    # Health -> SDG 3 "Good Health and Well-being"
r.resolve("20", "SEO2020", "SDG_PILLAR")  # -> "People" (SDG 3's parent pillar)
r.resolve("920101", "SEO2008", "SDG_GOAL")  # legacy vintage, via the same SEO2020 hub
```

The source table's own division numbering didn't match ours for 6 of 19 divisions (it used
a different/draft SEO2020 revision); resolved by matching on label instead of the source's
code, with two divisions given a direct user override where the source table had no
counterpart at all -- see the module docstring for the full account.

### Indigenous Studies (FOR2020 division 45): resolved via cultural proxy

ANZSRC's Indigenous Studies division (Aboriginal & Torres Strait Islander, Maori, and
Pacific Peoples research) has no direct OpenAlex/ASJC counterpart -- but its own group/field
labels are, almost entirely, a generic FOR2020 research concept with a population prefix
added ("Aboriginal and Torres Strait Islander history", "Pacific Peoples archaeology", a
Maori-language label with the English gloss in parens). `resolve()` reaches OAX/Leiden for
**2,201 of FOR2020's 2,203 codes** (exhaustively verified) by routing division-45 codes
through the non-Indigenous FOR2020 group or division representing that same concept, tagged
distinctly so it's never mistaken for official ANZSRC content or a real derived statistic:

```python
r.resolve("321207", "FOR1998", "OAX_FIELD")  # "Indigenous Health" -> OAX field 'Medicine'
                                              # match_method='cultural_proxy', confidence=0.51
```

As of this build, **all 2,203 FOR2020 codes resolve** -- exhaustively verified, including
group 4599 ("Other Indigenous studies"), the last remaining gap, proxied (with user
confirmation) to FOR2020 group 4499 "Other human society". Every FOR1998 and FOR2008 leaf
code that appears in its vintage bridge resolves too, since each first resolves to some
FOR2020 code and FOR2020 is now fully covered. See
`research_classification/curate_for2020_division45_to_proxy.py` for the full method, and
`tests/test_resolver.py`'s exhaustive coverage tests for the permanent regression guard.

### Legacy vintages also resolve at division/group level, not just leaf

FOR1998/FOR2008/SEO1998/SEO2008 all reach FOR2020/SEO2020 at division (2-digit) and group
(4-digit) precision too, not just leaf level (field/objective) -- derived by rolling up the
official leaf-level correspondence via majority vote (`research_classification/
build_correspondences_rollup.py`), since none of these four vintages' ABS source tables
publish anything coarser than leaf level directly:

```python
r.resolve("01", "FOR2008", "FOR2020")     # division -> "49 MATHEMATICAL SCIENCES"
r.resolve("0101", "FOR2008", "FOR2020")   # group -> "4904 Pure mathematics"
r.resolve("21", "FOR1998", "FOR2020")     # a genuine short code, not the padded "210000" --
                                           # both forms are accepted, see "Legacy code shapes" below
```

Coverage: FOR2008 is 100% at all three levels (22/22 division, 157/157 group, 1241/1241
field). FOR1998 is 100% at group/field (138/138, 895/895); division is 22/24 -- see below.
SEO2008 is 100% at all three levels (16/16, 109/109, 757/757); SEO1998 is 100% at all three
too (18/18, 107/107, 591/591). See `examples/map_category_for.py`/`map_category_seo.py` for
the full verification script, and `TODO.md` for how each gap was closed.

**Two FOR1998 divisions have no FOR2020 equivalent at all**, and `resolve()` says so rather
than raising: `21` "SCIENCE-GENERAL" and `22` "SOCIAL SCIENCES, HUMANITIES AND ARTS-GENERAL"
are broad catch-alls from the 1998 scheme with zero child disciplines of their own and no
matching general/multidisciplinary division anywhere in FOR2020's 23 divisions. For exactly
these two known, permanent cases, `resolve()` emits an informative `UserWarning` and returns
`None` instead of raising `LookupError` -- so `resolve()`'s return type is `CanonicalResult |
None`, and a caller iterating many codes should check for `None` alongside catching
`LookupError`:

```python
result = r.resolve("21", "FOR1998", "FOR2020")  # warns, returns None
if result is None:
    ...  # a known, documented absence -- not an error to handle specially
```

### Legacy code shapes: FOR1998/SEO1998 vs FOR2008/SEO2008

FOR2008/SEO2008 codes are natively variable-width (division `01`, group `0101`, field
`010101` -- each a distinct code, not padding). FOR1998/SEO1998 instead encode every level in
a single flat 6-digit space, right-padded with zeros for coarser levels (division `210000`,
discipline/group `230100`, leaf `230101`). `resolve()` accepts *either* shape for FOR1998/
SEO1998 -- the genuine short code (`"21"`, `"2301"`) or the ABS source's own zero-padded form
(`"210000"`, `"230100"`) -- normalizing internally before lookup.

### Precision: group-level (4-digit) when available, division-level otherwise

`resolve()` automatically uses FOR *group* precision (4-digit, e.g. `4905`) over *division*
precision (2-digit, e.g. `49`) whenever the input supports it, falling back gracefully when
it doesn't (partial coverage -- see `TODO.md`):

```python
r.resolve("4905", "FOR2020", "OAX_FIELD")  # group-level: confidence 0.69
r.resolve("49", "FOR2020", "OAX_FIELD")    # division-level fallback: confidence 0.61
r.resolve("1908", "OAX", "FOR2020")        # OAX subfield -> FOR2020 group (4-digit), not just division
```

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

### Bare-label lookups: ties resolve to the coarsest level

Resolving by label instead of code (e.g. `r.resolve("Transport", "SEO1998", "SEO2020")`) can
hit a genuine collision: the same label text can legitimately belong to more than one
`source_code` at different granularities (e.g. SEO1998 division `69` "TRANSPORT" and an
unrelated objective-level leaf `660403` also just labeled "Transport"). Since a bare-text
query carries no code, there's no basis to prefer a finer level over a coarser one sharing
the label -- `resolve()` always returns the coarsest match in that case, with the finer one
available via `.alternates`:

```python
result = r.resolve("Transport", "SEO1998", "SEO2020")
result.level, result.code  # ("division", "27") -- not the unrelated objective-level leaf
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

Needed if you're changing the source classification files themselves (`data_untracked/`,
not tracked in this repo), or if you see the `RuntimeWarning` described above and want to
refresh the bundled `.duckdb` file for the `duckdb` version you have installed. Requires the
`build` extra:

```
pip install -e ".[build]"
python build.py          # regenerates research_classification/data/*.csv AND *.duckdb
python tests/test_resolver.py
```
