"""Package conftest for tests/lambdas/ducklake_writer/handler/ (rec-2709 Wave 8).

Hoists the module-level autouse fixture `_reset_warm_connection` from the former
tests/test_ducklake_writer_handler.py monolith VERBATIM. Layers UNDER the root tests/conftest.py
(global recursion/socket/env-clearing autouse fixtures) without redeclaring any of them.
"""

import pytest

from src.common import ducklake_runtime as rt


@pytest.fixture(autouse=True)
def _reset_warm_connection():
    """The writer uses a per-container warm-connection global on the single-statement path (D2);
    reset it around every test so a cached connection never leaks between tests."""
    rt.reset_warm_connection()
    yield
    rt.reset_warm_connection()
