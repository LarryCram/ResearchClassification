"""Public resolver API.

Resolver() with no arguments loads the CSVs bundled inside this package (research_classification/data/)
into an in-memory DuckDB -- so `pip install git+https://github.com/LarryCram/ResearchClassification.git`
followed immediately by `Resolver().resolve(...)` just works, no separate build step and no
external data file required. Pass db_path=... to point at an exported .duckdb file instead
(e.g. one produced by build_duckdb.py) if you want that file's exact snapshot or faster
repeated startup across many short-lived processes.

`system` is always required, never inferred, since FOR/SEO/OAX codes collide with each other.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import duckdb

System = Literal["FOR", "SEO", "OAX"]

_CANONICAL_TABLE = {"FOR": "for_2020", "SEO": "seo_2020", "OAX": None}  # OAX spans 4 tables
_OAX_TABLES = ["openalex_domains", "openalex_fields", "openalex_subfields", "openalex_topics"]

_BRIDGE_TABLES = [
    "bridge_for2008_for2020",
    "bridge_seo2008_seo2020",
    "bridge_ford2015_for2020",
    "bridge_nabs2007_seo2020",
    "bridge_asrc1998_for2020",
    "bridge_asrc1998_seo2020",
    "bridge_asjc_openalex",
    "bridge_openalex_for",
    "bridge_leiden_openalex_topic",
    "bridge_leiden_openalex_domain",
    "bridge_leiden_for",
]

# The subset of _BRIDGE_TABLES whose source_code genuinely IS "a FOR/SEO code from some
# other year" -- i.e. could plausibly arrive as a bare code claiming to be FOR/SEO input,
# and so is worth hard-failing over if it collides with the current FOR2020/SEO2020 meaning.
# Deliberately excludes bridge_openalex_for/bridge_leiden_for/bridge_asjc_openalex/
# bridge_leiden_openalex_*: those represent a DIFFERENT classification system's own code
# (an OpenAlex field id, a Leiden main_field id) that WE curated/derived a mapping for --
# not a prior ANZSRC vintage -- so a coincidental digit-string collision with one of those
# isn't a real-world ambiguity a caller would ever actually hit (nobody hands this tool an
# OpenAlex field id and claims it's a FOR code), and hard-failing on it would only break the
# legitimate, intentional use of resolve(<leiden_main_field_id>, "FOR").
_VINTAGE_BRIDGE_TABLES: dict[System, list[str]] = {
    "FOR": ["bridge_asrc1998_for2020", "bridge_for2008_for2020", "bridge_ford2015_for2020"],
    "SEO": ["bridge_asrc1998_seo2020", "bridge_seo2008_seo2020", "bridge_nabs2007_seo2020"],
    "OAX": [],
}


@dataclass(frozen=True)
class CanonicalResult:
    input_value: str
    system: System
    canonical_code: str
    canonical_label: str
    canonical_level: str
    source_system: str
    match_method: str
    confidence: float
    alternates: tuple["CanonicalResult", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetResult:
    """One requested target's result from Resolver.resolve_forward(). If no mapping exists
    (only happens for FOR division 45, Indigenous Studies -- ANZSRC-specific, no counterpart
    anywhere in OpenAlex/ASJC's international taxonomy), code/label are empty and `method`
    is "unavailable" rather than raising, since that's a real answer ("there is none"), not
    a lookup failure."""

    code: str
    label: str
    level: str
    confidence: float
    method: str
    note: str = ""


_NO_MAPPING_NOTE = (
    "No OpenAlex/Leiden equivalent exists for this FOR division in the source data -- "
    "genuinely absent, not a lookup failure."
)


class AmbiguousCodeError(LookupError):
    """Raised when a bare code (no source_type given) matches more than one scheme with
    genuinely different canonical targets, and there's no way to tell which one was meant.

    This is real, not theoretical: RFCD1998 (pre-2000) and FOR2020 reused overlapping
    numeric ranges with unrelated meanings -- code 300101 is "Soil Physics" under RFCD1998
    but "Agricultural biotechnology diagnostics" under FOR2020. 48% of RFCD1998's 898 codes
    collide with a differently-meaning FOR2020 code this way. Silently preferring one
    interpretation (e.g. always the current FOR2020 meaning) would misclassify roughly half
    of all pre-2008 codes with false confidence=1.0 and no indication anything was wrong --
    so this hard-fails instead. Pass source_type= (e.g. "FOR20", matching ARC's own
    field-of-research/socio-economic-objective "type" tag) to resolve unambiguously.
    """

    def __init__(self, value: str, system: str, candidates: list["CanonicalResult"]):
        self.value = value
        self.system = system
        self.candidates = candidates
        lines = "\n".join(
            f"  - as {c.source_system}: {c.canonical_code} {c.canonical_label!r}" for c in candidates
        )
        super().__init__(
            f"{value!r} is ambiguous as a {system} code -- matches multiple schemes with "
            f"different meanings:\n{lines}\nPass source_type= to disambiguate (e.g. the "
            f"ARC field-of-research/socio-economic-objective JSON's own \"type\" value, "
            f"like \"FOR20\")."
        )


# Maps an explicit vintage hint to how it should be resolved. None means "this is already
# the current 2020 vintage -- search only the canonical table, not any bridge." A string
# means "this is a historical vintage -- search only bridge rows with this source_system."
# Only vintages actually confirmed against real data are listed; an unrecognized source_type
# raises rather than guessing (see resolve()'s docstring) -- add new entries here once their
# exact tag string is confirmed against real source data, don't guess in advance.
_SOURCE_TYPE_MAP: dict[str, tuple[System, str | None]] = {
    "FOR20": ("FOR", None),
    "SEO20": ("SEO", None),
}


class Resolver:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is not None:
            self._con = duckdb.connect(str(db_path), read_only=True)
        else:
            self._con = self._load_bundled_csvs()

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

    # -- internal lookups -------------------------------------------------

    def _canonical_identity(self, value: str, system: System) -> CanonicalResult | None:
        if system == "OAX":
            for table in _OAX_TABLES:
                row = self._con.execute(
                    f"SELECT code, level, label FROM {table} WHERE code = ?", [value]
                ).fetchone()
                if row:
                    code, level, label = row
                    return CanonicalResult(value, system, code, label, level, system, "identity", 1.0)
            return None
        table = _CANONICAL_TABLE[system]
        row = self._con.execute(f"SELECT code, level, label FROM {table} WHERE code = ?", [value]).fetchone()
        if not row:
            return None
        code, level, label = row
        return CanonicalResult(value, system, code, label, level, f"{system}2020", "identity", 1.0)

    def _canonical_label_match(self, value: str, system: System) -> CanonicalResult | None:
        tables = _OAX_TABLES if system == "OAX" else [_CANONICAL_TABLE[system]]
        for table in tables:
            row = self._con.execute(
                f"SELECT code, level, label FROM {table} WHERE lower(label) = lower(?)", [value]
            ).fetchone()
            if row:
                code, level, label = row
                source_system = system if system == "OAX" else f"{system}2020"
                return CanonicalResult(value, system, code, label, level, source_system, "identity", 1.0)
        return None

    def _bridge_lookup(
        self,
        value: str,
        system: System,
        by: str,
        source_system: str | None = None,
        tables: list[str] | None = None,
    ) -> list[CanonicalResult]:
        """Search bridge tables for a matching source_code (by='code') or case-insensitive
        source_label (by='label'), is_primary row first. If source_system is given, only
        rows from that specific source scheme are considered (used by the source_type-hinted
        path in resolve() to search one historical vintage exactly). If tables is given,
        only those bridge tables are searched (used to scope the no-hint ambiguity check to
        genuine ANZSRC vintages, see _VINTAGE_BRIDGE_TABLES); defaults to every bridge table."""
        where_col = "source_code = ?" if by == "code" else "lower(source_label) = lower(?)"
        source_filter = " AND source_system = ?" if source_system else ""
        params_extra = [source_system] if source_system else []
        hits: list[tuple[bool, CanonicalResult]] = []
        for table in (tables if tables is not None else _BRIDGE_TABLES):
            query = (
                f"SELECT source_system, canonical_code, canonical_label, canonical_level, "
                f"is_primary, match_method, confidence FROM {table} "
                f"WHERE system = ? AND {where_col}{source_filter}"
            )
            for source_sys, code, label, level, is_primary, match_method, confidence in self._con.execute(
                query, [system, value, *params_extra]
            ).fetchall():
                # bundled CSVs and exported .duckdb files are both loaded all_varchar=true,
                # so is_primary/confidence come back as strings -- bool("False") is True in
                # Python, so this must be a string comparison, not bool()
                result = CanonicalResult(
                    value, system, code, label, level, source_sys, match_method, float(confidence)
                )
                hits.append((str(is_primary).lower() == "true", result))
        hits.sort(key=lambda h: not h[0])
        return [result for _, result in hits]

    # -- public API ---------------------------------------------------------

    def resolve(self, value: str, system: System, source_type: str | None = None) -> CanonicalResult:
        """source_type is an optional vintage hint (e.g. "FOR20", matching the ARC field-
        of-research/socio-economic-objective JSON's own "type" tag) that restricts the
        search to exactly that scheme. Without it, a bare code that matches more than one
        scheme with genuinely different meanings raises AmbiguousCodeError rather than
        silently picking one -- see that class's docstring for why (RFCD1998/FOR2020 alone
        collide on 48% of RFCD1998's own codes)."""
        if system not in ("FOR", "SEO", "OAX"):
            raise ValueError(f"system must be one of FOR/SEO/OAX, got {system!r}")

        if source_type is not None:
            return self._resolve_with_hint(value, system, source_type)

        hit = self._resolve_unambiguous(value, system, by="code")
        if hit:
            return hit
        hit = self._resolve_unambiguous(value, system, by="label")
        if hit:
            return hit

        raise LookupError(f"{value!r} not found in {system} canonical or bridge tables")

    def _resolve_unambiguous(self, value: str, system: System, by: str) -> CanonicalResult | None:
        """Collect every interpretation of `value` -- canonical identity/label match, plus
        each genuine-ANZSRC-vintage bridge table's own best (is_primary) answer (see
        _VINTAGE_BRIDGE_TABLES) -- and hard-fail via AmbiguousCodeError if DIFFERENT SOURCE
        SCHEMES disagree on the canonical target, rather than silently preferring one. This
        is deliberately scoped to disagreement ACROSS schemes, not the ordinary within-one-
        scheme one-to-many case (e.g. a single RFCD1998 code with several partial-match
        alternates all under source_system=RFCD1998, which is the existing, legitimate
        is_primary/alternates pattern used throughout this pipeline and must NOT hard-fail).
        If neither the canonical table nor any vintage bridge matches at all, falls back to
        the full bridge set (OpenAlex/Leiden-derived included) with no ambiguity check, since
        those represent a different kind of mapping, not a colliding ANZSRC vintage."""
        identity_hit = (
            self._canonical_identity(value, system) if by == "code" else self._canonical_label_match(value, system)
        )
        vintage_tables = _VINTAGE_BRIDGE_TABLES.get(system, [])
        vintage_hits = self._bridge_lookup(value, system, by=by, tables=vintage_tables)

        # one representative (the primary) per distinct source_system, since _bridge_lookup
        # already sorts is_primary first within each table/source_system
        seen_schemes: set[str] = set()
        scheme_primaries: list[CanonicalResult] = []
        for hit in vintage_hits:
            if hit.source_system not in seen_schemes:
                seen_schemes.add(hit.source_system)
                scheme_primaries.append(hit)

        cross_scheme_candidates = ([identity_hit] if identity_hit else []) + scheme_primaries
        if cross_scheme_candidates:
            distinct_targets = {c.canonical_code for c in cross_scheme_candidates}
            if len(distinct_targets) > 1:
                seen_targets: set[str] = set()
                representatives = []
                for c in cross_scheme_candidates:
                    if c.canonical_code not in seen_targets:
                        seen_targets.add(c.canonical_code)
                        representatives.append(c)
                raise AmbiguousCodeError(value, system, representatives)

            if identity_hit:
                return identity_hit
            primary, *rest = vintage_hits
            return CanonicalResult(
                primary.input_value, primary.system, primary.canonical_code, primary.canonical_label,
                primary.canonical_level, primary.source_system, primary.match_method, primary.confidence,
                alternates=tuple(rest),
            )

        # nothing in the canonical table or any genuine vintage -- fall back to the full
        # bridge set (OpenAlex/Leiden-derived), no ambiguity check needed for these
        other_hits = self._bridge_lookup(value, system, by=by)
        if other_hits:
            primary, *rest = other_hits
            return CanonicalResult(
                primary.input_value, primary.system, primary.canonical_code, primary.canonical_label,
                primary.canonical_level, primary.source_system, primary.match_method, primary.confidence,
                alternates=tuple(rest),
            )
        return None

    def _resolve_with_hint(self, value: str, system: System, source_type: str) -> CanonicalResult:
        if source_type not in _SOURCE_TYPE_MAP:
            raise ValueError(
                f"Unrecognized source_type {source_type!r}. Known values: {sorted(_SOURCE_TYPE_MAP)}. "
                f"Guessing at an unconfirmed scheme mapping here would defeat the purpose of "
                f"passing a hint at all -- add the exact tag to _SOURCE_TYPE_MAP once its "
                f"meaning is confirmed against real source data."
            )
        hint_system, hint_source_system = _SOURCE_TYPE_MAP[source_type]
        if hint_system != system:
            raise ValueError(
                f"source_type={source_type!r} implies system={hint_system!r}, but "
                f"system={system!r} was requested"
            )

        if hint_source_system is None:
            # current vintage: canonical table only, never a bridge -- a bridge match here
            # would by definition be some OTHER scheme's code colliding numerically
            hit = self._canonical_identity(value, system) or self._canonical_label_match(value, system)
            if hit:
                return hit
            raise LookupError(
                f"{value!r} not found in the {system}2020 canonical table (source_type={source_type!r})"
            )

        bridge_hits = self._bridge_lookup(value, system, by="code", source_system=hint_source_system)
        if not bridge_hits:
            bridge_hits = self._bridge_lookup(value, system, by="label", source_system=hint_source_system)
        if bridge_hits:
            primary, *rest = bridge_hits
            return CanonicalResult(
                primary.input_value, primary.system, primary.canonical_code, primary.canonical_label,
                primary.canonical_level, primary.source_system, primary.match_method, primary.confidence,
                alternates=tuple(rest),
            )
        raise LookupError(f"{value!r} not found among {hint_source_system} entries (source_type={source_type!r})")

    def resolve_many(self, values: list[str], system: System, source_type: str | None = None) -> list[CanonicalResult]:
        return [self.resolve(v, system, source_type=source_type) for v in values]

    def resolve_forward(
        self,
        value: str,
        system: Literal["FOR", "SEO"],
        targets: tuple[str, ...] = ("FOR2020", "OAX", "Leiden"),
        source_type: str | None = None,
    ) -> dict[str, TargetResult]:
        """Map any valid code or label -- from any in-scope vintage (pre-2000 RFCD1998/
        SEO1998, FOR2008/SEO2008, FORD2015/NABS2007, or FOR2020/SEO2020 itself) -- forward to
        its FOR2020 (or SEO2020) equivalent, and from there up to its OpenAlex (OAX) and
        Leiden Main Field equivalents, per request via `targets`.

        Two invariants enforced throughout, matching how this whole pipeline is built:
        - Forward in time only: every hop moves from an older/coarser vintage toward
          FOR2020, never the reverse (e.g. this never goes FOR2020 -> FOR2008 -> RFCD1998).
        - Up the hierarchy only, never down: OAX/Leiden results are reported at whatever
          level the data honestly supports for a FOR *division* (OAX field, Leiden main
          field) -- never a fabricated OAX topic (1-of-4516) guess, since a division-level
          input can't honestly justify that much specificity.

        system="SEO" only ever returns a SEO2020 result -- OAX/Leiden are subject/topic
        classifications with no relationship to SEO by design (see project scope), so those
        targets come back as "unavailable" rather than a forced guess.

        source_type is the same optional vintage hint as resolve() -- pass it whenever you
        have it (e.g. ARC's own "type" tag) to avoid AmbiguousCodeError on a colliding code.
        """
        base = self.resolve(value, system, source_type=source_type)
        results: dict[str, TargetResult] = {}

        if "FOR2020" in targets or "SEO2020" in targets:
            key = f"{system}2020"
            results[key] = TargetResult(
                base.canonical_code, base.canonical_label, base.canonical_level,
                base.confidence, base.match_method,
            )

        if system == "SEO":
            for t in ("OAX", "Leiden"):
                if t in targets:
                    results[t] = TargetResult(
                        "", "", "", 0.0, "unavailable",
                        "SEO is an objective classification; OAX/Leiden are subject/topic "
                        "classifications with no relationship to SEO by design.",
                    )
            return results

        division_code = base.canonical_code[:2]  # up the hierarchy: always resolve via division

        if "OAX" in targets:
            row = self._con.execute(
                """
                SELECT openalex_field_id, openalex_field_label, share
                FROM for2020_division_openalex_field
                WHERE for_division_code = ? AND is_primary = 'True'
                """,
                [division_code],
            ).fetchone()
            if row:
                code, label, share = row
                results["OAX"] = TargetResult(code, label, "field", float(share), "derived_empirical")
            else:
                results["OAX"] = TargetResult("", "", "", 0.0, "unavailable", _NO_MAPPING_NOTE)

        if "Leiden" in targets:
            row = self._con.execute(
                """
                SELECT leiden_main_field_id, leiden_main_field_label, share
                FROM for2020_division_leiden_main_field
                WHERE for_division_code = ? AND is_primary = 'True'
                """,
                [division_code],
            ).fetchone()
            if row:
                code, label, share = row
                results["Leiden"] = TargetResult(code, label, "main_field", float(share), "derived_empirical")
            else:
                results["Leiden"] = TargetResult("", "", "", 0.0, "unavailable", _NO_MAPPING_NOTE)

        return results
