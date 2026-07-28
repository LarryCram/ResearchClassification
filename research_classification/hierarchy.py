"""Integrity checks shared by every canonical/bridge table in the pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

VALID_SYSTEMS = {"FOR", "SEO", "OAX"}

BRIDGE_COLUMNS = [
    "source_system",
    "source_code",
    "source_label",
    "system",
    "canonical_code",
    "canonical_label",
    "canonical_level",
    "is_primary",
    "match_method",
    "confidence",
    "notes",
]

MATCH_METHODS = {
    "identity",
    "explicit_official",
    "explicit_official_transitive",
    "exact_key_join",
    "derived_empirical",
    "manual_curated",
    "manual_override",
    "constrained_lexical",
    "exact_match",
    "contains_match",
    "below_floor",
    "lexical",
    "cultural_proxy",
    "user_provided",
    "user_provided_inverted",
}


def validate_canonical(
    df: pd.DataFrame,
    expected_total: int,
    name: str,
    require_prefix: bool = True,
    level_order: list[str] | None = None,
) -> None:
    """require_prefix=True proves parent-child structure AND acyclicity via strict
    decimal-nesting (holds for ANZSRC FOR/SEO and OpenAlex field->subfield). Where that
    nesting isn't guaranteed by the source scheme (e.g. OpenAlex domain->field, whose IDs
    are independent small integers), pass require_prefix=False and acyclicity is instead
    proven by a topological check (parents always precede children, no cycles possible in
    a table with this few levels since every non-root parent must already have level<child)."""
    assert len(df) == expected_total, f"{name}: expected {expected_total} rows, got {len(df)}"
    assert df["code"].is_unique, f"{name}: duplicate codes found"
    non_root = df[df["parent_code"] != ""]
    codes = set(df["code"])
    missing_parents = ~non_root["parent_code"].isin(codes)
    assert not missing_parents.any(), (
        f"{name}: orphan parent_code(s): "
        f"{non_root.loc[missing_parents, ['code', 'parent_code']].to_dict('records')}"
    )
    if require_prefix:
        bad_prefix = ~non_root.apply(lambda r: r["code"].startswith(r["parent_code"]), axis=1)
        assert not bad_prefix.any(), (
            f"{name}: code does not start with parent_code for "
            f"{non_root.loc[bad_prefix, ['code', 'parent_code']].to_dict('records')}"
        )
    else:
        assert level_order, f"{name}: level_order is required when require_prefix=False"
        level_rank = {lvl: i for i, lvl in enumerate(level_order)}
        assert df["level"].map(level_rank).notna().all(), f"{name}: unknown level value present"
        parent_level = df.set_index("code")["level"].map(level_rank).to_dict()
        bad_order = non_root.apply(
            lambda r: parent_level.get(r["parent_code"], -1) >= level_rank[r["level"]], axis=1
        )
        assert not bad_order.any(), f"{name}: parent_code does not precede child level"


def validate_bridge(df: pd.DataFrame, canonical_lookup: dict[str, set[str]], name: str) -> None:
    assert list(df.columns) == BRIDGE_COLUMNS, f"{name}: unexpected columns {list(df.columns)}"
    assert df["system"].isin(VALID_SYSTEMS).all(), f"{name}: invalid system value(s) present"
    assert df["match_method"].isin(MATCH_METHODS).all(), f"{name}: invalid match_method value(s)"
    assert df["confidence"].between(0, 1).all(), f"{name}: confidence out of [0,1]"

    primaries = df.groupby(["source_system", "source_code", "system"])["is_primary"].sum()
    bad = primaries[primaries != 1]
    assert bad.empty, f"{name}: expected exactly one is_primary per source-code group, found:\n{bad}"

    for system, sub in df.groupby("system"):
        valid_codes = canonical_lookup.get(system, set())
        unknown = ~sub["canonical_code"].isin(valid_codes)
        assert not unknown.any(), (
            f"{name}: canonical_code(s) not found in {system} canonical table: "
            f"{sub.loc[unknown, 'canonical_code'].unique().tolist()}"
        )


def audit_encoding(df: pd.DataFrame, path: str) -> list[tuple[str, str, int, str, int]]:
    """Scan every string column for non-ASCII characters. Returns
    (file, column, row_index, character, codepoint) for each occurrence, printed for review."""
    findings: list[tuple[str, str, int, str, int]] = []
    for col in df.columns:
        # Don't filter by dtype: pandas 3.x defaults string columns to a "str"/Arrow-backed
        # dtype rather than legacy "object", so an `== object` check silently skips every
        # column. The isinstance check below is the real filter.
        for idx, val in df[col].items():
            if not isinstance(val, str):
                continue
            for ch in val:
                if ord(ch) > 127:
                    findings.append((path, col, idx, ch, ord(ch)))
    return findings


def write_csv(df: pd.DataFrame, path: Path, sort_by: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values(sort_by).to_csv(path, index=False, encoding="utf-8")
