"""Public resolver API. Backed by data/research_classification.duckdb -- a single portable
file (built once by build.py) rather than re-parsing a dozen CSVs on every call. system is
always required, never inferred, since FOR/SEO/OAX codes collide with each other."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "research_classification.duckdb"

System = Literal["FOR", "SEO", "OAX"]

_CANONICAL_TABLE = {"FOR": "for_2020", "SEO": "seo_2020", "OAX": None}  # OAX spans 4 tables
_OAX_TABLES = ["openalex_domains", "openalex_fields", "openalex_subfields", "openalex_topics"]

_con: duckdb.DuckDBPyConnection | None = None


def _connection() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"{DB_PATH} not found -- run `python build.py` first to build it."
            )
        _con = duckdb.connect(str(DB_PATH), read_only=True)
    return _con


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


def _canonical_identity(con: duckdb.DuckDBPyConnection, value: str, system: System) -> CanonicalResult | None:
    if system == "OAX":
        for table in _OAX_TABLES:
            row = con.execute(
                f"SELECT code, level, label FROM {table} WHERE code = ?", [value]
            ).fetchone()
            if row:
                code, level, label = row
                return CanonicalResult(value, system, code, label, level, f"{system}", "identity", 1.0)
        return None
    table = _CANONICAL_TABLE[system]
    row = con.execute(f"SELECT code, level, label FROM {table} WHERE code = ?", [value]).fetchone()
    if not row:
        return None
    code, level, label = row
    return CanonicalResult(value, system, code, label, level, f"{system}2020", "identity", 1.0)


def _canonical_label_match(con: duckdb.DuckDBPyConnection, value: str, system: System) -> CanonicalResult | None:
    tables = _OAX_TABLES if system == "OAX" else [_CANONICAL_TABLE[system]]
    for table in tables:
        row = con.execute(
            f"SELECT code, level, label FROM {table} WHERE lower(label) = lower(?)", [value]
        ).fetchone()
        if row:
            code, level, label = row
            source_system = system if system == "OAX" else f"{system}2020"
            return CanonicalResult(value, system, code, label, level, source_system, "identity", 1.0)
    return None


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


def _bridge_lookup(con: duckdb.DuckDBPyConnection, value: str, system: System, by: str) -> list[CanonicalResult]:
    """Search every bridge table for a matching source_code (by='code') or case-insensitive
    source_label (by='label'), returning matches with the is_primary row first."""
    where_col = "source_code = ?" if by == "code" else "lower(source_label) = lower(?)"
    hits: list[tuple[bool, CanonicalResult]] = []
    for table in _BRIDGE_TABLES:
        query = (
            f"SELECT source_system, canonical_code, canonical_label, canonical_level, "
            f"is_primary, match_method, confidence FROM {table} WHERE system = ? AND {where_col}"
        )
        for source_system, code, label, level, is_primary, match_method, confidence in con.execute(
            query, [system, value]
        ).fetchall():
            # the DuckDB tables are loaded all_varchar=true (see build_duckdb.py), so
            # is_primary/confidence come back as strings here, not native bool/float --
            # bool("False") is True in Python, so this must be a string comparison, not bool()
            result = CanonicalResult(
                value, system, code, label, level, source_system, match_method, float(confidence)
            )
            hits.append((str(is_primary).lower() == "true", result))
    hits.sort(key=lambda h: not h[0])
    return [result for _, result in hits]


def resolve(value: str, system: System) -> CanonicalResult:
    if system not in ("FOR", "SEO", "OAX"):
        raise ValueError(f"system must be one of FOR/SEO/OAX, got {system!r}")
    con = _connection()

    hit = _canonical_identity(con, value, system)
    if hit:
        return hit

    bridge_hits = _bridge_lookup(con, value, system, by="code")
    if bridge_hits:
        primary, *rest = bridge_hits
        return CanonicalResult(
            primary.input_value, primary.system, primary.canonical_code, primary.canonical_label,
            primary.canonical_level, primary.source_system, primary.match_method, primary.confidence,
            alternates=tuple(rest),
        )

    hit = _canonical_label_match(con, value, system)
    if hit:
        return hit

    bridge_hits = _bridge_lookup(con, value, system, by="label")
    if bridge_hits:
        primary, *rest = bridge_hits
        return CanonicalResult(
            primary.input_value, primary.system, primary.canonical_code, primary.canonical_label,
            primary.canonical_level, primary.source_system, primary.match_method, primary.confidence,
            alternates=tuple(rest),
        )

    raise LookupError(f"{value!r} not found in {system} canonical or bridge tables")


def resolve_many(values: list[str], system: System) -> list[CanonicalResult]:
    return [resolve(v, system) for v in values]


@dataclass(frozen=True)
class TargetResult:
    """One requested target's result from resolve_forward(). If no mapping exists (only
    happens for FOR division 45, Indigenous Studies -- ANZSRC-specific, no counterpart
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


def resolve_forward(
    value: str, system: Literal["FOR", "SEO"], targets: tuple[str, ...] = ("FOR2020", "OAX", "Leiden")
) -> dict[str, TargetResult]:
    """Map any valid code or label -- from any in-scope vintage (pre-2000 RFCD1998/SEO1998,
    FOR2008/SEO2008, FORD2015/NABS2007, or FOR2020/SEO2020 itself) -- forward to its FOR2020
    (or SEO2020) equivalent, and from there up to its OpenAlex (OAX) and Leiden Main Field
    equivalents, per request via `targets`.

    Two invariants enforced throughout, matching how this whole pipeline is built:
    - Forward in time only: every hop moves from an older/coarser vintage toward FOR2020,
      never the reverse (e.g. this never goes FOR2020 -> FOR2008 -> RFCD1998).
    - Up the hierarchy only, never down: OAX/Leiden results are reported at whatever level
      the data honestly supports for a FOR *division* (OAX field/domain, Leiden main field)
      -- never a fabricated OAX topic (1-of-4516) guess, since a division-level input can't
      honestly justify that much specificity.

    system="SEO" only ever returns a SEO2020 result -- OAX/Leiden are subject/topic
    classifications with no relationship to SEO by design (see project scope), so those
    targets come back as "unavailable" rather than a forced guess.
    """
    con = _connection()
    base = resolve(value, system)
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
        row = con.execute(
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
        row = con.execute(
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
