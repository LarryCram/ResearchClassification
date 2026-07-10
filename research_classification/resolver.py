"""Public resolver API.

Resolver() with no arguments opens the pre-built research_classification.duckdb bundled
inside this package (research_classification/data/) directly, read-only -- so `pip install
git+https://github.com/LarryCram/ResearchClassification.git` followed immediately by
`Resolver().resolve(...)` just works, no separate build step and no external data file
required. This is ~10ms (vs ~360ms rebuilding an in-memory database from the 28 bundled CSVs
on every call), so it's the default; the CSVs stay bundled too as an automatic fallback (see
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

FromScheme = Literal["OAX", "FOR1998", "FOR2008", "FOR2020", "SEO1998", "SEO2008", "SEO2020"]
ToScheme = Literal[
    "OAX_DOMAIN", "OAX_FIELD", "OAX_SUBFIELD", "OAX_TOPIC", "FOR2020", "SEO2020", "LEIDEN",
    "SDG_GOAL", "SDG_PILLAR",
]

_VALID_FROM_SCHEMES = {"OAX", "FOR1998", "FOR2008", "FOR2020", "SEO1998", "SEO2008", "SEO2020"}
_VALID_TO_SCHEMES = {
    "OAX_DOMAIN", "OAX_FIELD", "OAX_SUBFIELD", "OAX_TOPIC", "FOR2020", "SEO2020", "LEIDEN",
    "SDG_GOAL", "SDG_PILLAR",
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
_NATIVE_LENGTHS: dict[str, set[int]] = {
    "FOR1998": {6},
    "FOR2008": {6},
    "FOR2020": {2, 4, 6},
    "SEO1998": {6},
    "SEO2008": {6},
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
    "LEIDEN": ("for2020_division_leiden_main_field", "leiden_main_field_id", "leiden_main_field_label", "main_field"),
}

_GROUP_CENTRIC: dict[str, tuple[str, str, str, str]] = {
    to_scheme: (table.replace("for2020_division_", "for2020_group_"), code_col, label_col, level)
    for to_scheme, (table, code_col, label_col, level) in _DIVISION_CENTRIC.items()
}

_OAX_LEVEL_TABLE = {"domain": "openalex_domains", "field": "openalex_fields", "subfield": "openalex_subfields", "topic": "openalex_topics"}
_OAX_LEVEL_RANK = {"domain": 0, "field": 1, "subfield": 2, "topic": 3}
_TO_SCHEME_OAX_LEVEL = {"OAX_DOMAIN": "domain", "OAX_FIELD": "field", "OAX_SUBFIELD": "subfield", "OAX_TOPIC": "topic"}

_NO_MAPPING_NOTE = (
    "No OpenAlex/Leiden equivalent exists for this FOR division in the source data, and no "
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
        db_resource = importlib.resources.files("research_classification") / "data" / "research_classification.duckdb"
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
        data_dir = importlib.resources.files("research_classification") / "data"
        for csv_path in sorted(p for p in data_dir.iterdir() if p.name.endswith(".csv")):
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
            rows = self._con.execute(
                "SELECT canonical_code, canonical_label, canonical_level, is_primary, match_method, confidence "
                f"FROM {table} WHERE lower(source_label) = lower(?) ORDER BY is_primary DESC",
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

    def resolve(self, value: str | int, from_scheme: FromScheme, to_scheme: ToScheme) -> CanonicalResult:
        if from_scheme not in _VALID_FROM_SCHEMES:
            raise ValueError(f"from_scheme must be one of {sorted(_VALID_FROM_SCHEMES)}, got {from_scheme!r}")
        if to_scheme not in _VALID_TO_SCHEMES:
            raise ValueError(f"to_scheme must be one of {sorted(_VALID_TO_SCHEMES)}, got {to_scheme!r}")

        code = self._normalize_code(value, from_scheme)

        if from_scheme in _SEO_VINTAGES:
            if to_scheme == "SEO2020":
                return self._resolve_vintage_to_current(code, from_scheme, "SEO")
            if to_scheme in ("SDG_GOAL", "SDG_PILLAR"):
                return self._resolve_seo_to_sdg(code, from_scheme, to_scheme)
            raise ValueError(
                f"from_scheme={from_scheme!r} can only target to_scheme='SEO2020', 'SDG_GOAL', or "
                f"'SDG_PILLAR' -- SEO is an objective classification with no relationship to OAX/Leiden "
                f"by design"
            )

        if from_scheme in _FOR_VINTAGES:
            if to_scheme == "FOR2020":
                return self._resolve_vintage_to_current(code, from_scheme, "FOR")
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
        if to_scheme == "LEIDEN":
            return self._resolve_oax_to_leiden(code)
        if to_scheme in _TO_SCHEME_OAX_LEVEL:
            return self._resolve_oax_to_oax(code, to_scheme)
        raise ValueError(f"from_scheme='OAX' cannot target to_scheme={to_scheme!r}")

    def resolve_many(
        self, values: list[str | int], from_scheme: FromScheme, to_scheme: ToScheme
    ) -> list[CanonicalResult]:
        return [self.resolve(v, from_scheme, to_scheme) for v in values]

    # -- FOR-family -> OAX/Leiden, via the FOR2020-division hub -------------

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
                f"SELECT {code_col}, {label_col}, share FROM {table} WHERE for_group_code = ? AND is_primary = 'True'",
                [group_code],
            ).fetchone()
            if row:
                out_code, out_label, share = row
                return CanonicalResult(input_value, from_scheme, to_scheme, out_code, out_label, level, "derived_empirical", float(share))

        division_code = for2020_code[:2]
        table, code_col, label_col, level = _DIVISION_CENTRIC[to_scheme]
        row = self._con.execute(
            f"SELECT {code_col}, {label_col}, share FROM {table} WHERE for_division_code = ? AND is_primary = 'True'",
            [division_code],
        ).fetchone()
        if row:
            out_code, out_label, share = row
            return CanonicalResult(input_value, from_scheme, to_scheme, out_code, out_label, level, "derived_empirical", float(share))

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

    # -- OAX -> FOR2020 / Leiden / OAX ---------------------------------------

    def _resolve_oax_to_for2020(self, code: str) -> CanonicalResult:
        identified = self._oax_identify(code)
        if not identified:
            raise LookupError(f"{code!r} not found in any OAX table (domain/field/subfield/topic)")
        oax_code, level, label, parent_code = identified
        if _OAX_LEVEL_RANK[level] < _OAX_LEVEL_RANK["field"]:
            raise ValueError(
                f"cannot resolve FOR2020 from an OAX {level}-level input ({code!r}) -- the curated "
                f"OpenAlex-field-to-FOR-division mapping needs at least field-level precision"
            )

        # subfield-or-deeper input tries the finer group-level seed first (walking up to
        # subfield if given a topic), falling back to the field-level/division-level seed
        if _OAX_LEVEL_RANK[level] >= _OAX_LEVEL_RANK["subfield"]:
            subfield_code, _subfield_label = self._oax_walk_up_simple(oax_code, level, "subfield")
            row = self._con.execute(
                "SELECT canonical_code, canonical_label, canonical_level, confidence "
                "FROM bridge_openalex_for_group WHERE source_code = ? AND is_primary = 'True'",
                [subfield_code],
            ).fetchone()
            if row:
                group_code, group_label, group_level, confidence = row
                return CanonicalResult(code, "OAX", "FOR2020", group_code, group_label, group_level, "constrained_lexical", float(confidence))

        field_code, _field_label = self._oax_walk_up_simple(oax_code, level, "field")
        row = self._con.execute(
            "SELECT canonical_code, canonical_label, canonical_level, confidence "
            "FROM bridge_openalex_for WHERE source_code = ? AND is_primary = 'True'",
            [field_code],
        ).fetchone()
        if not row:
            raise LookupError(f"{code!r} (OpenAlex field {field_code}): no curated FOR2020 mapping found")
        for_code, for_label, for_level, confidence = row
        return CanonicalResult(code, "OAX", "FOR2020", for_code, for_label, for_level, "manual_curated", float(confidence))

    def _resolve_oax_to_leiden(self, code: str) -> CanonicalResult:
        for2020 = self._resolve_oax_to_for2020(code)
        return self._resolve_from_for2020_code(code, for2020.code, "LEIDEN", "OAX")

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
