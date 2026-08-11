"""Package-scoped, non-autouse factory fixture for tests/validate/ (Decision 131 clause 3).

Thin wrapper over tests.fixtures.pre_sequence_stub.select_steps -- a pure function, so sharing
one instance for the whole package is safe. Non-autouse: nothing here fires unless a test
explicitly requests the ``pre_sequence_stub`` fixture, so editing it does not trip
affected_tests.py's full-suite forcing (that keys on the root conftest path alone).

The caller still does the patching itself, inside its own ``with (...)`` block alongside its
other patches -- e.g. ``patch("scripts.checks.registry.pre_sequence", return_value=steps)`` --
so the derived selection stays a factory callable inside the test body, not a class-level
fixture marker (a class-scoped patch could not exempt a single parametrized case). Selection
controls which checks scripts/validate.py's main() iterates; it does not by itself stop a
selected check's real body from running -- that still needs an explicit
``patch("validate.<name>")`` per Decision 131 clause 3's PR1/PR2 split.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from tests.fixtures.pre_sequence_stub import select_steps


@pytest.fixture(scope="package")
def pre_sequence_stub():
    """Factory: ``pre_sequence_stub(checks=(...), scaffolds="all")`` returns the derived Step
    list for the --pre tier. Callers patch scripts.checks.registry.pre_sequence with the result
    themselves (see module docstring)."""

    def _factory(*, checks: Iterable[str] = (), scaffolds: str | tuple[str, ...] = "all"):
        return select_steps(checks=tuple(checks), scaffolds=scaffolds, sequence="pre")

    return _factory
