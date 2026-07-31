"""Package-scoped fixtures for the validate_ci_refresh_read_coverage tests (Decision 131 sub-conftest).

Holds the one fixture both concern-split modules need. It is deliberately NOT autouse:
test_real_tree.py::test_real_tree_passes must run every production rule unmodified against the
production policy.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from scripts.checks.iam_tf._write_coverage import WRITE_COVERAGE

# WHY THE SYNTHETIC TREES ARE EXEMPT FROM A RULE THE REAL TREE SATISFIES (read before "fixing" this):
#
# design (c) rule 2 (_write_symmetry.check_read_write_scope_parity) requires each write-managed type's
# READ grant to cover everything its WRITE grant can create. This package's fixtures deliberately pair
# PREFIX write grants (function:agent-platform-*, secret:agent-platform-*, rule/agent-platform-*) with
# LITERAL read ARNs (agent-platform-known-fn, agent-platform-known-secret-*, ...). That mismatch IS the
# test apparatus: it is the only reason gap_fn / gap_secret / orphan_role are detectable as read gaps.
# Widening the fixtures' reads to the write prefixes would make every gap resource covered and delete
# the read-gap cases this package exists to test; narrowing their writes below the discovered prefixes
# would fail design (a) discovery. The two obligations are jointly unsatisfiable for THIS fixture, so
# rule 2 is neutralised for the synthetic trees ONLY.
#
# Production is untouched: READ_SCOPE_PARITY_EXEMPT still carries exactly one real entry
# (aws_iam_role), the real tree is asserted against the unpatched rule by
# test_real_tree.py::test_real_tree_passes, and rule 2's own positive/negative cases live in
# tests/checks/iam_tf/test__write_symmetry.py. Never widen the production exemption table, the
# transitive-skip set, or the rule to make a synthetic fixture green.
_SYNTHETIC_PARITY_WHY = (
    "SYNTHETIC-FIXTURE EXEMPTION (tests only): this fixture pairs prefix WRITE grants with literal "
    "READ ARNs on purpose, because that is what makes its read-gap resources detectable -- see the "
    "comment above this constant in conftest.py. The real tree is asserted against the UNPATCHED rule."
)


@pytest.fixture
def synthetic_parity_exempt() -> Iterator[None]:
    """Neutralise design (c) rule 2 for a synthetic fixture tree, and only for it."""
    exemptions = {rtype: _SYNTHETIC_PARITY_WHY for rtype in WRITE_COVERAGE}
    with patch.dict("scripts.checks.iam_tf._write_symmetry.READ_SCOPE_PARITY_EXEMPT", exemptions, clear=False):
        yield
