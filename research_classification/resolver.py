"""Public resolver API.

Resolver() with no arguments opens the pre-built research_classification.duckdb bundled
inside this package (research_classification/data/output/) directly, read-only -- so `pip
install git+https://github.com/LarryCram/ResearchClassification.git` followed immediately by
`Resolver().resolve(...)` just works, no separate build step and no external data file
required. This is ~10ms (vs ~360ms rebuilding an in-memory database from the bundled
canonical/bridge/hub CSVs under research_classification/data/intermediate/ on every call), so
it's the default; the CSVs stay bundled too as an automatic fallback (see
_load_bundled_db()'s docstring) and remain the git-diffable source of truth build.py rebuilds
from. Pass db_path=... to point at a different exported .duckdb file instead if you want a
specific file's exact snapshot.

Both `from_scheme` and `to_scheme` are always required, never inferred -- codes collide
across schemes and vintages (e.g. FOR1998's 300101 is "Soil Physics", FOR2020's own 300101
is "Agricultural biotechnology diagnostics" -- 48% of FOR1998's 898 codes collide with a
differently-meaning FOR2020 code this way), so guessing which scheme a bare code came from
is unsafe. Naming the scheme explicitly removes the guesswork by construction.
"""

from __future__ import annotations

import importlib.resources
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import duckdb

from .paths import DUCKDB_SOURCE_SUBDIR_NAMES

FromScheme = Literal["OAX", "FOR1998", "FOR2008", "FOR2020", "SEO1998", "SEO2008", "SEO2020"]
ToScheme = Literal[
    "OAX_DOMAIN", "OAX_FIELD", "OAX_SUBFIELD", "OAX_TOPIC", "FOR2020", "SEO2020",
    "FOR2020_AREA5", "SDG_GOAL", "SDG_PILLAR",
]

_VALID_FROM_SCHEMES = {"OAX", "FOR1998", "FOR2008", "FOR2020", "SEO1998", "SEO2008", "SEO2020"}
_VALID_TO_SCHEMES = {
    "OAX_DOMAIN", "OAX_FIELD", "OAX_SUBFIELD", "OAX_TOPIC", "FOR2020", "SEO2020",
    "FOR2020_AREA5", "SDG_GOAL", "SDG_PILLAR",
}
_FOR_VINTAGES = {"FOR1998", "FOR2008", "FOR2020"}
_SEO_VINTAGES = {"SEO1998", "SEO2008", "SEO2020"}

# Native code length(s) per from_scheme, used to recover a leading zero lost to integer
# conversion (common when codes pass through pandas/JSON/Excel without being read as text).
# FOR/SEO codes are always exactly 2, 4, or 6 digits; since no two of those differ by 1, an
# observed length of 1, 3, or 5 can only mean "lost its leading zero" -- unambiguous. OAX's
# four levels are natively 1/2/4/5 digits and never start with 0 in the actual data (domain
# 1-4, field 11-36, subfield/topic prefixed by those), so no correction is needed there, but
# the same length-based logic is still applied defensively.
# FOR2008/SEO2008 are genuinely 2/4/6-digit at the source (division/group/leaf each have
# their own code, not a shared padded width) -- all four of bridge_for2008_for2020.csv,
# bridge_for1998_for2020.csv, bridge_seo2008_seo2020.csv, and bridge_seo1998_seo2020.csv now
# carry division/group rows too (see build_correspondences_rollup.py), derived by rolling up
# the official leaf-level correspondence since none of these four vintages' ABS source
# publishes anything coarser. FOR1998/SEO1998 are listed here for documentation only: their
# own encoding is a flat 6-digit space with right-padding (FOR1998 division "210000",
# discipline "230100"; SEO1998 subdivision "610000", group "610100"), so length alone can't
# identify a division/group input the way it does for FOR2008/SEO2008 -- see the dedicated
# stripping branch in _normalize_code below, which handles both before this table is ever
# consulted for them.
_NATIVE_LENGTHS: dict[str, set[int]] = {
    "FOR1998": {2, 4, 6},
    "FOR2008": {2, 4, 6},
    "FOR2020": {2, 4, 6},
    "SEO1998": {2, 4, 6},
    "SEO2008": {2, 4, 6},
    "SEO2020": {2, 4, 6},
    "OAX": {1, 2, 4, 5},
}

# from_scheme -> bridge table to search (None means "canonical table directly, no bridge")
_VINTAGE_BRIDGE_TABLE: dict[str, str | None] = {
    "FOR1998": "bridge_for1998_for2020",
    "FOR2008": "bridge_for2008_for2020",
    "FOR2020": None,
    "SEO1998": "bridge_seo1998_seo2020",
    "SEO2008": "bridge_seo2008_seo2020",
    "SEO2020": None,
}

# to_scheme -> (division-centric table, code column, label column, result level label).
# Group-centric tables (one level finer, ~91% group coverage -- missing only division 45
# Indigenous Studies' groups, which have no OpenAlex equivalent at any granularity) are
# tried first when the FOR2020 code in hand has at least group-level (4-digit) precision;
# these division-level tables are always the fallback, and the only option below group level.
_DIVISION_CENTRIC: dict[str, tuple[str, str, str, str]] = {
    "OAX_DOMAIN": ("for2020_division_openalex_domain", "openalex_domain_id", "openalex_domain_label", "domain"),
    "OAX_FIELD": ("for2020_division_openalex_field", "openalex_field_id", "openalex_field_label", "field"),
    "OAX_SUBFIELD": ("for2020_division_openalex_subfield", "openalex_subfield_id", "openalex_subfield_label", "subfield"),
}

_GROUP_CENTRIC: dict[str, tuple[str, str, str, str]] = {
    to_scheme: (table.replace("for2020_division_", "for2020_group_"), code_col, label_col, level)
    for to_scheme, (table, code_col, label_col, level) in _DIVISION_CENTRIC.items()
}

# Codes confirmed to have no FOR2020 equivalent at all -- not a lookup gap to eventually
# close, a genuine, fully-diagnosed absence: checked every one of FOR2020's 23 divisions and
# none is a general/multidisciplinary catch-all, and both of these FOR1998 divisions have
# zero child disciplines/subjects of their own to derive a target from either (confirmed
# against data_untracked/12970_1998_2008.xlsx). resolve() warns and returns None for these
# rather than raising, so a caller iterating many codes isn't forced into a try/except for a
# known, permanent absence. See TODO.md.
_KNOWN_UNRESOLVABLE: dict[tuple[str, str], str] = {
    ("FOR1998", "21"): (
        "FOR1998 division 21 'SCIENCE-GENERAL' has no FOR2020 equivalent -- FOR2020 has no "
        "general/multidisciplinary catch-all division, and this 1998 division has zero child "
        "disciplines/subjects to derive one from. See TODO.md."
    ),
    ("FOR1998", "22"): (
        "FOR1998 division 22 'SOCIAL SCIENCES, HUMANITIES AND ARTS-GENERAL' has no FOR2020 "
        "equivalent -- FOR2020 has no general/multidisciplinary catch-all division, and this "
        "1998 division has zero child disciplines/subjects to derive one from. See TODO.md."
    ),
}

# OAX -> FOR2020 tiers, finest first: (OAX level required for this tier's lookup, bridge
# table keyed on that level's own code). Each bridge is algorithmic/cascade-generated (not
# the hand-curated FOR2020->OAX direction's _DIVISION_CENTRIC/_GROUP_CENTRIC), and each was
# audited to confidence -- see curate_openalex_for.py, curate_openalex_subfield_to_for_group.py,
# curate_openalex_topic_to_for_field.py.
_OAX_TO_FOR2020_TIERS: list[tuple[str, str]] = [
    ("topic", "bridge_openalex_for_topic"),      # -> FOR2020 field (6-digit)
    ("subfield", "bridge_openalex_for_group"),   # -> FOR2020 group (4-digit)
    ("field", "bridge_openalex_for"),            # -> FOR2020 division (2-digit)
]

_OAX_LEVEL_TABLE = {"domain": "openalex_domains", "field": "openalex_fields", "subfield": "openalex_subfields", "topic": "openalex_topics"}
_OAX_LEVEL_RANK = {"domain": 0, "field": 1, "subfield": 2, "topic": 3}
_TO_SCHEME_OAX_LEVEL = {"OAX_DOMAIN": "domain", "OAX_FIELD": "field", "OAX_SUBFIELD": "subfield", "OAX_TOPIC": "topic"}

_NO_MAPPING_NOTE = (
    "No OpenAlex equivalent exists for this FOR division in the source data, and no "
    "match_method='cultural_proxy' fallback applies either -- genuinely absent, not a lookup "
    "failure. (As of this build, every FOR2020 code -- including all of division 45, "
    "Indigenous Studies, via curate_for2020_division45_to_proxy.py -- resolves; this message "
    "would only fire for a genuinely new, uncurated gap.) See TODO.md."
)


@dataclass(frozen=True)
class CanonicalResult:
    input_value: str
    from_scheme: FromScheme
    to_scheme: ToScheme
    code: str
    label: str
    level: str
    match_method: str
    confidence: float
    alternates: tuple["CanonicalResult", ...] = field(default_factory=tuple)


class Resolver:
    def __init__(self, db_path: str | Path | None = None):
        self._resource_ctx = None  # keeps an as_file()-extracted temp path alive, if any
        if db_path is not None:
            self._con = duckdb.connect(str(db_path), read_only=True)
        else:
            self._con = self._load_bundled_db()

    def _load_bundled_db(self) -> duckdb.DuckDBPyConnection:
        """Opens the pre-built .duckdb file bundled in package data directly (~10ms),
        falling back to rebuilding in-memory from the bundled CSVs (~360ms, but always
        works) if that file can't be opened -- e.g. it was built with a different duckdb
        version than whatever's installed now. DuckDB's on-disk storage format isn't
        guaranteed compatible indefinitely across versions, and this package is meant to be
        pip-installed unmodified into new environments over a period of years, so this isn't
        a hypothetical: the fallback exists specifically so a version mismatch degrades to
        "slower" rather than "broken"."""
        db_resource = (
            importlib.resources.files("research_classification")
            / "data" / "output" / "research_classification.duckdb"
        )
        ctx = importlib.resources.as_file(db_resource)
        real_path = ctx.__enter__()
        try:
            con = duckdb.connect(str(real_path), read_only=True)
        except duckdb.Error as e:
            ctx.__exit__(None, None, None)
            warnings.warn(
                f"Could not open the bundled research_classification.duckdb ({e}); falling back to "
                "rebuilding in-memory from the bundled CSVs (slower, but unaffected by duckdb version "
                "drift). To silence this, rebuild the .duckdb file with the currently-installed duckdb "
                "version (python build.py, or research_classification.build_duckdb.run()).",
                RuntimeWarning,
                stacklevel=2,
            )
            return self._load_bundled_csvs()
        self._resource_ctx = ctx  # keep the (usually no-op) extracted path alive for self's lifetime
        return con

    @staticmethod
    def _load_bundled_csvs() -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        data_dir = importlib.resources.files("research_classification") / "data" / "intermediate"
        # canonical/bridges/hub only -- seeds/ holds cache/input artifacts for the build
        # pipeline's curate_*.py scripts, not resolver-queryable tables (this matches
        # pre-restructure behavior, where seeds/ lived outside data/ entirely and was never
        # bundled here either). Same three names build_duckdb.py loads via DUCKDB_SOURCE_DIRS.
        for subdir_name in DUCKDB_SOURCE_SUBDIR_NAMES:
            subdir = data_dir / subdir_name
            for csv_path in sorted(p for p in subdir.iterdir() if p.name.endswith(".csv")):
                table = csv_path.name.removesuffix(".csv")
                with importlib.resources.as_file(csv_path) as real_path:
                    con.execute(
                        f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto(?, header=true, all_varchar=true)",
                        [str(real_path)],
                    )
        return con

    # -- normalization ------------------------------------------------------

    @staticmethod
    def _normalize_code(value: str | int, from_scheme: str) -> str:
        text = str(value)
        if not text.isdigit():
            return text  # a label, not a code -- leave untouched
        if from_scheme in ("FOR1998", "SEO1998"):
            # Both encode every level in a flat 6-digit space, right-padded with zeros for
            # coarser levels (FOR1998: division ends "0000", discipline/group ends "00" but
            # not "0000"; SEO1998: subdivision ends "0000", group ends "00" but not "0000").
            # Recover a lost leading zero on that padded form first (length 5 -> 6, same
            # logic as below), then strip the padding to the level's own genuine short code
            # -- "210000" -> "21", "230100" -> "2301" -- which is what
            # bridge_for1998_for2020.csv/bridge_seo1998_seo2020.csv are actually keyed on for
            # those levels (leaf/field codes never end in "00", so they pass through
            # unchanged).
            if len(text) == 5:
                text = "0" + text
            if len(text) == 6:
                if text.endswith("0000"):
                    return text[:2]
                if text.endswith("00"):
                    return text[:4]
            return text
        native_lengths = _NATIVE_LENGTHS.get(from_scheme, set())
        if len(text) in native_lengths:
            return text
        if (len(text) + 1) in native_lengths:
            return "0" + text
        return text  # doesn't match a known native length; let lookup fail with a clear message

    # -- FOR2020 / SEO2020 resolution (from a vintage, or identity) --------

    def _resolve_current_vintage(self, value: str, family_system: str) -> CanonicalResult:
        """family_system is 'FOR' or 'SEO'. Resolves against the FOR2020/SEO2020 canonical
        table directly, by code then by case-insensitive label."""
        table = "for_2020" if family_system == "FOR" else "seo_2020"
        row = self._con.execute(f"SELECT code, level, label FROM {table} WHERE code = ?", [value]).fetchone()
        if not row:
            row = self._con.execute(
                f"SELECT code, level, label FROM {table} WHERE lower(label) = lower(?)", [value]
            ).fetchone()
        if not row:
            raise LookupError(f"{value!r} not found in the {family_system}2020 canonical table")
        code, level, label = row
        to_scheme = "FOR2020" if family_system == "FOR" else "SEO2020"
        return CanonicalResult(value, to_scheme, to_scheme, code, label, level, "identity", 1.0)

    def _resolve_vintage_to_current(self, value: str, from_scheme: str, family_system: str) -> CanonicalResult:
        table = _VINTAGE_BRIDGE_TABLE[from_scheme]
        to_scheme = "FOR2020" if family_system == "FOR" else "SEO2020"
        if table is None:
            result = self._resolve_current_vintage(value, family_system)
            return CanonicalResult(value, from_scheme, to_scheme, result.code, result.label, result.level, result.match_method, result.confidence)

        rows = self._con.execute(
            "SELECT canonical_code, canonical_label, canonical_level, is_primary, match_method, confidence "
            f"FROM {table} WHERE source_code = ? ORDER BY is_primary DESC",
            [value],
        ).fetchall()
        if not rows:
            # A bare label can collide across source_codes at different levels (e.g. SEO1998
            # division 69 "TRANSPORT" and an unrelated objective-level leaf 660403 both
            # literally labeled "Transport") -- is_primary alone doesn't break that tie, since
            # each row IS the correct primary for its own, different source_code. Prefer the
            # coarsest (shortest source_code) match: a bare-text query carries no code, so
            # there's no basis for picking a finer level over a coarser one that shares the
            # same label -- every FOR/SEO scheme's code precision is consistent (2/4/6 digits
            # = division/group/field-or-objective), so LENGTH(source_code) ASC is a reliable
            # coarsest-first tiebreak everywhere this query runs.
            rows = self._con.execute(
                "SELECT canonical_code, canonical_label, canonical_level, is_primary, match_method, confidence "
                f"FROM {table} WHERE lower(source_label) = lower(?) "
                "ORDER BY is_primary DESC, LENGTH(source_code) ASC",
                [value],
            ).fetchall()
        if not rows:
            raise LookupError(f"{value!r} not found among {from_scheme} entries")

        results = [
            CanonicalResult(value, from_scheme, to_scheme, code, label, level, method, float(confidence))
            for code, label, level, _is_primary, method, confidence in rows
        ]
        primary, *rest = results
        return CanonicalResult(
            primary.input_value, primary.from_scheme, primary.to_scheme, primary.code, primary.label,
            primary.level, primary.match_method, primary.confidence, alternates=tuple(rest),
        )

    # -- SEO -> SDG (division-level, user-provided) --------------------------

    def _resolve_seo_to_sdg(self, code: str, from_scheme: FromScheme, to_scheme: ToScheme) -> CanonicalResult:
        seo2020 = self._resolve_vintage_to_current(code, from_scheme, "SEO")
        division_code = seo2020.code[:2]
        row = self._con.execute(
            "SELECT sdg_code, sdg_label, confidence FROM seo2020_division_sdg WHERE seo2020_division_code = ?",
            [division_code],
        ).fetchone()
        if not row:
            raise LookupError(f"{code!r} (SEO2020 division {division_code}): no SDG mapping found")
        goal_code, goal_label, confidence = row

        if to_scheme == "SDG_GOAL":
            return CanonicalResult(code, from_scheme, to_scheme, goal_code, goal_label, "goal", "user_provided", float(confidence))

        # SDG_PILLAR: walk up the exact, official goal->pillar hierarchy fact in sdg.csv --
        # not a separately-derived estimate, so it carries the same confidence as the goal.
        pillar_row = self._con.execute("SELECT parent_code FROM sdg WHERE code = ? AND level = 'goal'", [goal_code]).fetchone()
        pillar_code = pillar_row[0]
        pillar_label = self._con.execute("SELECT label FROM sdg WHERE code = ? AND level = 'pillar'", [pillar_code]).fetchone()[0]
        return CanonicalResult(code, from_scheme, to_scheme, pillar_code, pillar_label, "pillar", "user_provided", float(confidence))

    # -- FOR -> FOR2020_AREA5 (division-level, user-provided) ----------------
    #
    # A direct FOR2020 division -> area fact, not a bridge/cascade -- plays the same role
    # CWTS Leiden's main_field used to play (a coarse, top-level grouping above the FOR
    # divisions) but without the old indirect FOR2020 -> OAX -> Leiden derivation loop.

    def _area5_result(self, input_value: str, from_scheme: FromScheme, for2020_code: str) -> CanonicalResult:
        division_code = for2020_code[:2]
        row = self._con.execute(
            "SELECT area5_code, area5_label FROM for2020_area5 WHERE for2020_division_code = ?",
            [division_code],
        ).fetchone()
        if not row:
            raise LookupError(f"FOR2020 division {division_code!r}: no FOR2020_AREA5 mapping found")
        area_code, area_label = row
        return CanonicalResult(input_value, from_scheme, "FOR2020_AREA5", area_code, area_label, "area", "user_provided", 1.0)

    def _resolve_for_to_area5(self, code: str, from_scheme: FromScheme) -> CanonicalResult:
        for2020 = self._resolve_vintage_to_current(code, from_scheme, "FOR")
        return self._area5_result(code, from_scheme, for2020.code)

    def _resolve_oax_to_area5(self, code: str) -> CanonicalResult:
        for2020 = self._resolve_oax_to_for2020(code)
        return self._area5_result(code, "OAX", for2020.code)

    # -- OAX hierarchy walking (up only) ------------------------------------

    def _oax_identify(self, value: str) -> tuple[str, str, str, str] | None:
        """Returns (code, level, label, parent_code) for a bare OAX-family code/label,
        checking all four levels (their code ranges never overlap: domain 1-4, field 11-36,
        subfield/topic prefixed by those, so at most one table ever matches)."""
        for level, table in _OAX_LEVEL_TABLE.items():
            row = self._con.execute(f"SELECT code, label, parent_code FROM {table} WHERE code = ?", [value]).fetchone()
            if row:
                return row[0], level, row[1], row[2]
        for level, table in _OAX_LEVEL_TABLE.items():
            row = self._con.execute(
                f"SELECT code, label, parent_code FROM {table} WHERE lower(label) = lower(?)", [value]
            ).fetchone()
            if row:
                return row[0], level, row[1], row[2]
        return None

    # -- public API -----------------------------------------------------

    def resolve(self, value: str | int, from_scheme: FromScheme, to_scheme: ToScheme) -> CanonicalResult | None:
        if from_scheme not in _VALID_FROM_SCHEMES:
            raise ValueError(f"from_scheme must be one of {sorted(_VALID_FROM_SCHEMES)}, got {from_scheme!r}")
        if to_scheme not in _VALID_TO_SCHEMES:
            raise ValueError(f"to_scheme must be one of {sorted(_VALID_TO_SCHEMES)}, got {to_scheme!r}")

        code = self._normalize_code(value, from_scheme)

        reason = _KNOWN_UNRESOLVABLE.get((from_scheme, code))
        if reason is not None:
            warnings.warn(reason, UserWarning, stacklevel=2)
            return None

        if from_scheme in _SEO_VINTAGES:
            if to_scheme == "SEO2020":
                return self._resolve_vintage_to_current(code, from_scheme, "SEO")
            if to_scheme in ("SDG_GOAL", "SDG_PILLAR"):
                return self._resolve_seo_to_sdg(code, from_scheme, to_scheme)
            raise ValueError(
                f"from_scheme={from_scheme!r} can only target to_scheme='SEO2020', 'SDG_GOAL', or "
                f"'SDG_PILLAR' -- SEO is an objective classification with no relationship to OAX "
                f"by design"
            )

        if from_scheme in _FOR_VINTAGES:
            if to_scheme == "FOR2020":
                return self._resolve_vintage_to_current(code, from_scheme, "FOR")
            if to_scheme == "FOR2020_AREA5":
                return self._resolve_for_to_area5(code, from_scheme)
            if to_scheme == "OAX_TOPIC":
                raise ValueError(
                    "to_scheme='OAX_TOPIC' is never supported from a FOR-family input -- OpenAlex's "
                    "4,516 topics are far finer than anything honestly derivable from a FOR division; "
                    "the finest OAX granularity available this way is 'OAX_SUBFIELD'"
                )
            if to_scheme in _DIVISION_CENTRIC:
                return self._resolve_from_for_division_hub(code, from_scheme, to_scheme)
            raise ValueError(f"from_scheme={from_scheme!r} cannot target to_scheme={to_scheme!r}")

        # from_scheme == "OAX"
        if to_scheme == "FOR2020":
            return self._resolve_oax_to_for2020(code)
        if to_scheme == "FOR2020_AREA5":
            return self._resolve_oax_to_area5(code)
        if to_scheme in _TO_SCHEME_OAX_LEVEL:
            return self._resolve_oax_to_oax(code, to_scheme)
        raise ValueError(f"from_scheme='OAX' cannot target to_scheme={to_scheme!r}")

    def resolve_many(
        self, values: list[str | int], from_scheme: FromScheme, to_scheme: ToScheme
    ) -> list[CanonicalResult]:
        return [self.resolve(v, from_scheme, to_scheme) for v in values]

    # -- FOR-family -> OAX, via the FOR2020-division hub --------------------

    def _resolve_from_for2020_code(
        self, input_value: str, for2020_code: str, to_scheme: ToScheme, from_scheme: FromScheme
    ) -> CanonicalResult:
        """Given an already-resolved FOR2020 code -- division (2-digit) or group (4-digit)
        precision -- resolve into to_scheme via the group-centric table when group-level
        precision is available (falling back to division-level if that group has no
        coverage, e.g. it's one of division 45's), else division-centric directly."""
        if len(for2020_code) >= 4:
            group_code = for2020_code[:4]
            table, code_col, label_col, level = _GROUP_CENTRIC[to_scheme]
            row = self._con.execute(
                f"SELECT {code_col}, {label_col}, share, match_method FROM {table} "
                "WHERE for_group_code = ? AND is_primary = 'True'",
                [group_code],
            ).fetchone()
            if row:
                out_code, out_label, share, match_method = row
                return CanonicalResult(input_value, from_scheme, to_scheme, out_code, out_label, level, match_method, float(share))

        division_code = for2020_code[:2]
        table, code_col, label_col, level = _DIVISION_CENTRIC[to_scheme]
        row = self._con.execute(
            f"SELECT {code_col}, {label_col}, share, match_method FROM {table} "
            "WHERE for_division_code = ? AND is_primary = 'True'",
            [division_code],
        ).fetchone()
        if row:
            out_code, out_label, share, match_method = row
            return CanonicalResult(input_value, from_scheme, to_scheme, out_code, out_label, level, match_method, float(share))

        if division_code == "45":
            # Tries the exact code first (covers the 451901-451907 field-level overrides,
            # and a direct query of bare "45" or bare "4519"), then its group prefix (covers
            # the 18 themed groups 4501-4518, and 4519's own NEC field falling through to
            # 4519's group-level default). Deliberately does NOT fall back any further -- an
            # unmapped group like 4599 stays a hard LookupError, not silently swallowed by
            # the division-wide default.
            proxy = self._con.execute(
                "SELECT proxy_code, confidence FROM for2020_division45_group_to_proxy WHERE for2020_source_code = ?",
                [for2020_code],
            ).fetchone()
            if not proxy and len(for2020_code) > 4:
                proxy = self._con.execute(
                    "SELECT proxy_code, confidence FROM for2020_division45_group_to_proxy WHERE for2020_source_code = ?",
                    [for2020_code[:4]],
                ).fetchone()
            if proxy:
                proxy_code, proxy_confidence = proxy
                proxied = self._resolve_from_for2020_code(input_value, proxy_code, to_scheme, from_scheme)
                return CanonicalResult(
                    input_value, from_scheme, to_scheme, proxied.code, proxied.label, proxied.level,
                    "cultural_proxy", round(proxied.confidence * float(proxy_confidence), 3),
                )

        raise LookupError(f"{input_value!r} (FOR2020 division {division_code}): {_NO_MAPPING_NOTE}")

    def _resolve_from_for_division_hub(self, code: str, from_scheme: FromScheme, to_scheme: ToScheme) -> CanonicalResult:
        result = self._resolve_vintage_to_current(code, from_scheme, "FOR")
        return self._resolve_from_for2020_code(code, result.code, to_scheme, from_scheme)

    # -- OAX -> FOR2020 / FOR2020_AREA5 / OAX --------------------------------

    def _resolve_oax_to_for2020(self, code: str) -> CanonicalResult:
        """Tries the finest OAX precision the input actually supports first, cascading to
        progressively coarser tiers -- topic -> field (leaf), subfield -> group, field ->
        division -- stopping at the first tier with a confident (non-below_floor) row. A
        below_floor/confidence-0 hit at any tier means "no trustworthy answer here", not "the
        answer": it's still recorded in that tier's own bridge CSV (for anyone inspecting the
        raw data), but resolve() itself always prefers a trustworthy coarser answer over an
        untrustworthy finer one -- the same graceful-degradation philosophy used everywhere
        else in this module. The field->division tier is the guaranteed final fallback: after
        the OAX subfield->FOR group audit (see curate_openalex_subfield_to_for_group.py's
        docstring), every one of bridge_openalex_for.csv's 26 rows has real confidence, so
        this tier never itself returns below_floor and the trailing LookupError below is
        unreachable in practice, kept only as a defensive final guard."""
        identified = self._oax_identify(code)
        if not identified:
            raise LookupError(f"{code!r} not found in any OAX table (domain/field/subfield/topic)")
        oax_code, level, label, parent_code = identified
        if _OAX_LEVEL_RANK[level] < _OAX_LEVEL_RANK["field"]:
            raise ValueError(
                f"cannot resolve FOR2020 from an OAX {level}-level input ({code!r}) -- the curated "
                f"OpenAlex-field-to-FOR-division mapping needs at least field-level precision"
            )

        for required_level, table in _OAX_TO_FOR2020_TIERS:
            if _OAX_LEVEL_RANK[level] < _OAX_LEVEL_RANK[required_level]:
                continue  # input is coarser than this tier needs -- try a coarser tier instead
            lookup_code = oax_code if level == required_level else self._oax_walk_up_simple(oax_code, level, required_level)[0]
            row = self._con.execute(
                f"SELECT canonical_code, canonical_label, canonical_level, match_method, confidence "
                f"FROM {table} WHERE source_code = ? AND is_primary = 'True'",
                [lookup_code],
            ).fetchone()
            if row and row[3] != "below_floor" and float(row[4]) > 0:
                for_code, for_label, for_level, match_method, confidence = row
                return CanonicalResult(code, "OAX", "FOR2020", for_code, for_label, for_level, match_method, float(confidence))

        raise LookupError(f"{code!r}: no curated FOR2020 mapping found at any OAX precision tier")

    def _resolve_oax_to_oax(self, code: str, to_scheme: ToScheme) -> CanonicalResult:
        identified = self._oax_identify(code)
        if not identified:
            raise LookupError(f"{code!r} not found in any OAX table (domain/field/subfield/topic)")
        oax_code, level, label, _parent_code = identified
        target_level = _TO_SCHEME_OAX_LEVEL[to_scheme]
        out_code, out_label = self._oax_walk_up_simple(oax_code, level, target_level)
        # walking parent_code is an exact hierarchy fact, not a derived/empirical estimate,
        # whether it's a same-level identity match or a walk up to a coarser ancestor
        return CanonicalResult(code, "OAX", to_scheme, out_code, out_label, target_level, "identity", 1.0)

    def _oax_walk_up_simple(self, code: str, level: str, target_level: str) -> tuple[str, str]:
        if _OAX_LEVEL_RANK[target_level] > _OAX_LEVEL_RANK[level]:
            raise ValueError(
                f"cannot resolve OAX {level} {code!r} down to {target_level} -- one {level} contains "
                f"many {target_level}s, not derivable uniquely (up the hierarchy only)"
            )
        cur_code, cur_level = code, level
        _parent_of = {"field": "domain", "subfield": "field", "topic": "subfield"}
        while cur_level != target_level:
            table = _OAX_LEVEL_TABLE[cur_level]
            row = self._con.execute(f"SELECT parent_code FROM {table} WHERE code = ?", [cur_code]).fetchone()
            cur_code, cur_level = row[0], _parent_of[cur_level]
        label_row = self._con.execute(f"SELECT label FROM {_OAX_LEVEL_TABLE[cur_level]} WHERE code = ?", [cur_code]).fetchone()
        return cur_code, label_row[0]
