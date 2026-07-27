"""Shared fixture for the tests/checks/deps/affected_tests/ concern-split package.

write_file() is copied verbatim from the former tests/checks/deps/test_affected_tests.py
monolith's module-level `_write()` helper (Decision 128 SLOC decomposition). Used by every
concern-split module in the package. tests/fixtures/ is an importable package exempt from the
no-cross-test-import guard (names never start with test_) -- consumers alias on import (e.g.
`from tests.fixtures.affected_tests_helpers import write_file as _write`) so every call site
stays byte-identical to the monolith. Direct precedent: tests/fixtures/ops_writer_helpers.py.
"""

from __future__ import annotations

from pathlib import Path


def write_file(root: Path, relpath: str, content: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
