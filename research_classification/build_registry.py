from __future__ import annotations

import pandas as pd

from .hierarchy import write_csv
from .paths import CANONICAL_DIR

# Static "Rosetta stone" of how every scheme's levels line up by granularity.
# rank=1 is the coarsest level within that scheme. cardinality/corresponds_to are filled
# in once the relevant tables exist (build.py calls run() after build_for_seo/build_openalex/
# build_asjc/build_for_area5 so the counts below are always live, not guessed).
_ROWS = [
    ("FOR", "division", 1, "2-digit", ""),
    ("FOR", "group", 2, "4-digit", ""),
    ("FOR", "field", 3, "6-digit", ""),
    ("SEO", "division", 1, "2-digit", ""),
    ("SEO", "group", 2, "4-digit", ""),
    ("SEO", "objective", 3, "6-digit", ""),
    ("OAX", "domain", 1, "1-digit", ""),
    ("OAX", "field", 2, "2-digit", "ASJC field code (exact)"),
    ("OAX", "subfield", 3, "4-digit", "ASJC subfield code (exact)"),
    ("OAX", "topic", 4, "5-digit", ""),
    ("ASJC", "field", 2, "2-digit", "= OAX field_id (exact)"),
    ("ASJC", "subfield", 3, "4-digit", "superset of OAX subfield_id (252 of 361 used)"),
    ("FOR2020_AREA5", "area", 1, "label", "direct FOR2020 division -> area fact, user-provided"),
]


_SOURCE_FILES = {
    ("FOR", "division"): ("for_2020.csv", "division"),
    ("FOR", "group"): ("for_2020.csv", "group"),
    ("FOR", "field"): ("for_2020.csv", "field"),
    ("SEO", "division"): ("seo_2020.csv", "division"),
    ("SEO", "group"): ("seo_2020.csv", "group"),
    ("SEO", "objective"): ("seo_2020.csv", "objective"),
    ("OAX", "domain"): ("openalex_domains.csv", None),
    ("OAX", "field"): ("openalex_fields.csv", None),
    ("OAX", "subfield"): ("openalex_subfields.csv", None),
    ("OAX", "topic"): ("openalex_topics.csv", None),
    ("ASJC", "field"): ("asjc.csv", "field"),
    ("ASJC", "subfield"): ("asjc.csv", "subfield"),
    ("FOR2020_AREA5", "area"): ("for2020_area5.csv", None),
}


def _live_cardinalities() -> dict[tuple[str, str], int]:
    cardinalities: dict[tuple[str, str], int] = {}
    for key, (fname, level_filter) in _SOURCE_FILES.items():
        path = CANONICAL_DIR / fname
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        cardinalities[key] = len(df[df["level"] == level_filter]) if level_filter else len(df)
    return cardinalities


def run(cardinalities: dict[tuple[str, str], int] | None = None) -> pd.DataFrame:
    cardinalities = cardinalities if cardinalities is not None else _live_cardinalities()
    rows = []
    for scheme, level, rank, code_form, corresponds_to in _ROWS:
        rows.append(
            {
                "scheme": scheme,
                "level": level,
                "rank": rank,
                "code_form": code_form,
                "cardinality": cardinalities.get((scheme, level), ""),
                "corresponds_to": corresponds_to,
            }
        )
    df = pd.DataFrame(rows)
    write_csv(df, CANONICAL_DIR / "scheme_registry.csv", ["scheme", "rank"])
    return df


if __name__ == "__main__":
    df = run()
    print(df)
