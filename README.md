# research-classification

Harmonized research classification lookup: ANZSRC FOR/SEO (2020, 2008, and pre-2000
RFCD1998/SEO1998), OpenAlex's topic hierarchy, Scopus ASJC, and the CWTS Leiden Ranking
Main Fields, resolved into three canonical systems (`FOR`, `SEO`, `OAX`).

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

# any code or label, from any in-scope vintage, to its FOR2020/SEO2020/OAX equivalent
r.resolve("230104", "FOR")          # RFCD1998 (pre-2000) code
r.resolve("010101", "FOR")          # FOR2008 code
r.resolve("Chemistry", "OAX")       # label, current scheme

# forward-chain a code/label all the way to FOR2020 + OpenAlex + Leiden Main Field
r.resolve_forward("230104", "FOR")
# {'FOR2020': TargetResult(code='490403', label='Category theory...', confidence=0.9, ...),
#  'OAX':     TargetResult(code='26', label='Mathematics', level='field', confidence=0.61),
#  'Leiden':  TargetResult(code='5', label='Mathematics and computer science', confidence=0.67)}
```

`system` is always required (`"FOR"`, `"SEO"`, or `"OAX"`) -- codes collide across systems,
so it's never inferred. `resolve_forward` only ever moves forward in time (toward FOR2020,
never back to an older vintage) and up the hierarchy (OAX capped at *field* level, Leiden at
*main field* -- never a fabricated guess at one of OpenAlex's 4,516 fine-grained topics).
See `examples/map_category_to_leiden.py` for a fuller worked example, including handling
free-text category columns that don't match any code/label exactly.

If a mapping genuinely doesn't exist (e.g. ANZSRC's Indigenous Studies division has no
counterpart anywhere in OpenAlex/ASJC's international taxonomy), the result says so
explicitly (`method="unavailable"`, with a `note`) rather than guessing or raising.

## Rebuilding the data

Only needed if you're changing the source classification files themselves
(`data_untracked/`, not tracked in this repo). Requires the `build` extra:

```
pip install -e ".[build]"
python build.py          # regenerates research_classification/data/*.csv
python tests/test_resolver.py
```
