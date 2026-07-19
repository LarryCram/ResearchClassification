"""Single source of truth for every on-disk location this package's build pipeline and
resolver touch. Introduced when data/ was split into raw/intermediate/output subfolders,
replacing ~17 modules that each independently redefined ROOT/DATA_DIR/SEEDS_DIR.

Directory semantics (why four kinds under intermediate/, not one flat folder):
- canonical/: pure derivations from raw source data, no human judgment involved.
- bridges/: the validated 11-column BRIDGE_COLUMNS schema (see hierarchy.py).
- hub/: FOR2020-division/group-centric derived tables (their own share/is_primary schema,
  not BRIDGE_COLUMNS).
- seeds/: cache-guarded, human/LLM-reviewed curation results that curate_*.py scripts check
  for before regenerating -- inputs that happen to be cached outputs of a prior run, never
  silently overwritten. Kept distinct from bridges/ for exactly that reason.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_ROOT = ROOT / "research_classification" / "data"
RAW_DIR = DATA_ROOT / "raw"
INTERMEDIATE_DIR = DATA_ROOT / "intermediate"
CANONICAL_DIR = INTERMEDIATE_DIR / "canonical"
BRIDGES_DIR = INTERMEDIATE_DIR / "bridges"
HUB_DIR = INTERMEDIATE_DIR / "hub"
SEEDS_DIR = INTERMEDIATE_DIR / "seeds"
OUTPUT_DIR = DATA_ROOT / "output"
DB_PATH = OUTPUT_DIR / "research_classification.duckdb"

# The three subtrees build_duckdb.py loads into tables (seeds/ is deliberately excluded --
# it holds cache/input artifacts, not resolver-queryable tables, matching pre-restructure
# behavior where seeds/ lived outside data/ entirely and was never bundled).
DUCKDB_SOURCE_DIRS = [CANONICAL_DIR, BRIDGES_DIR, HUB_DIR]

# NOTE: every raw source the build pipeline reads now lives under RAW_DIR (git-tracked) --
# the project is self-contained, no gitignored data_untracked/ dependency remains in code.
