"""Shared fixtures for the tests/ops_writer/ concern-split package.

make_writer() and VALID_REC are copied verbatim from the former tests/test_ops_writer.py
monolith's module-level `_make_writer()` factory and `_VALID_REC` dict (rec-2709 Wave 9).
make_writer() is used by all five ops_writer concern-split modules; VALID_REC is used by
test_write.py (TestOpsWriterWrite, TestRecsT219Rejection) and test_outbox_emit.py
(TestOpsWriterOutbox). VALID_REC is only ever copied (`{**VALID_REC}`) or read, never mutated
in place, so a shared module-level constant is safe. tests/fixtures/ is an importable package
exempt from the no-cross-test-import guard (names never start with test_) -- consumers alias on
import (e.g. `from tests.fixtures.ops_writer_helpers import make_writer as _make_writer`) so
every call site and dict-spread stays byte-identical to the monolith. Direct precedent: Wave 3's
tests/fixtures/ops_portal_records.py.
"""

from __future__ import annotations


def make_writer():
    """Return an OpsWriter with a fresh instance (no cached boto3 client)."""
    from scripts.ops_writer import OpsWriter

    return OpsWriter()


# All fields required by the OpsWriter backstop guard.
VALID_REC = {
    "id": "rec-001",
    "status": "open",
    "title": "Test recommendation",
    "source": "manual",
    "effort": "S",
    "priority": "Low",
    "file": "scripts/test.py",
    "context": "Testing context",
    "acceptance": "Tests pass",
}
