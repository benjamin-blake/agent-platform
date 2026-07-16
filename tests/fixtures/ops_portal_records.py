"""Shared data constants for the tests/ops_data_portal/ concern-split package.

VALID_FIELDS and VALID_DECISION_FIELDS are copied verbatim from the former
tests/test_ops_data_portal.py monolith's _VALID_FIELDS / _VALID_DECISION_FIELDS dicts (rec-2709
Wave 3). Both are always copied (dict(...) or {**...}) by every consumer, never mutated in
place, so a single shared module-level definition is safe. tests/fixtures/ is an importable
package exempt from the no-cross-test-import guard (names never start with test_) -- consumers
alias on import (e.g. `from tests.fixtures.ops_portal_records import VALID_FIELDS as
_VALID_FIELDS`) so every method body that references `_VALID_FIELDS` stays byte-identical.
"""

from __future__ import annotations

VALID_FIELDS = {
    "title": "Test recommendation",
    "file": "scripts/ops_data_portal.py",
    "context": "This is a test rec context with enough detail to satisfy the 80-character minimum requirement.",
    "acceptance": "grep -q 'ops_data_portal' scripts/ops_data_portal.py",
    "effort": "XS",
    "priority": "Low",
    "source": "planning",
    "risk": "low",
    "status": "open",
    "automatable": True,
}

VALID_DECISION_FIELDS = {
    "title": "Test decision",
    "status": "open",
    "decision_id": 56,
}
