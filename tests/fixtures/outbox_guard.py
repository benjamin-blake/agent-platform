"""Pure snapshot/diff helper for the tests/conftest.py outbox hermeticity guard.

Kept importable outside conftest so tests/test_outbox_hermeticity_guard.py can unit-test the
detection logic directly. Re-points at src/common/outbox_retirement.py, the sole home of the
retired-table classification (Decision 84 I-4) -- no subtraction, no locally-derived copy.
"""

from __future__ import annotations

from pathlib import Path

from src.common.outbox_retirement import is_retired_dir

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTBOX_BASE = REPO_ROOT / "logs" / ".ops-outbox"


def snapshot(base: Path = OUTBOX_BASE) -> frozenset[Path]:
    """Return the set of files currently under *base*, or an empty set if it does not exist."""
    if not base.exists():
        return frozenset()
    return frozenset(p for p in base.rglob("*") if p.is_file())


def diff_new_files(before: frozenset[Path], after: frozenset[Path]) -> frozenset[Path]:
    """Return files present in *after* but not in *before*."""
    return after - before


def retired_files(paths: frozenset[Path], base: Path = OUTBOX_BASE) -> frozenset[Path]:
    """Filter *paths* to those under a retired-table (or *_pending) subdirectory of *base*."""
    retired = set()
    for path in paths:
        try:
            rel = path.relative_to(base)
        except ValueError:
            continue
        if rel.parts and is_retired_dir(rel.parts[0]):
            retired.add(path)
    return frozenset(retired)
