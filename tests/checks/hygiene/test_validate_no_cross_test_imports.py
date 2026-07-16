"""Tests for validate_no_cross_test_imports() (Decision 131 no-cross-test-import guard).

Placed at its MIRROR location (tests/checks/hygiene/ mirrors scripts/checks/hygiene/) to
demonstrate the new convention -- check_test_file_exists is still satisfied by
tests/test_validate.py under the live grandfather (scripts/checks/** -> tests/test_validate.py),
exactly as the existing tests/checks/test_validate_prose_allowlist.py already relies on.

Imports only from scripts.checks.hygiene -- never from another test module (it must pass its
own guard).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.hygiene.validate_no_cross_test_imports import (
    _find_violations,
    validate_no_cross_test_imports,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindViolations:
    """Exercises the pure _find_violations(paths) core directly on synthetic temp files."""

    def test_cross_test_module_import_is_flagged(self, tmp_path: Path) -> None:
        """`from tests.test_foo import X` -- the canonical violation shape."""
        path = _write(tmp_path, "tests/test_a.py", "from tests.test_foo import X\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1
        assert "test_a.py" in violations[0]

    def test_bare_import_of_a_test_module_is_flagged(self, tmp_path: Path) -> None:
        """`import tests.test_foo` -- ast.Import, not ast.ImportFrom."""
        path = _write(tmp_path, "tests/test_b.py", "import tests.test_foo\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_relative_import_of_a_test_name_is_flagged(self, tmp_path: Path) -> None:
        """`from . import test_helper` -- module is None, the imported name itself is checked."""
        path = _write(tmp_path, "tests/checks/test_c.py", "from . import test_helper\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_conftest_import_not_flagged(self, tmp_path: Path) -> None:
        """conftest.py never starts with test_ -- exempt by construction."""
        path = _write(tmp_path, "tests/test_d.py", "from tests.conftest import Y\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_fixtures_package_import_not_flagged(self, tmp_path: Path) -> None:
        """tests/fixtures/** never starts with test_ -- exempt by construction."""
        path = _write(tmp_path, "tests/test_e.py", "from tests.fixtures.helper import Z\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_grandfathered_path_is_exempt(self, tmp_path: Path) -> None:
        """tests/test_verifier_harness.py is in _GRANDFATHERED_CROSS_TEST_IMPORTS -- exempt
        even though its content would otherwise be flagged."""
        path = _write(
            tmp_path,
            "tests/test_verifier_harness.py",
            "from tests.test_verifiers.test_harness import test_run_all_verifiers\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_non_test_module_import_not_flagged(self, tmp_path: Path) -> None:
        """An ordinary production-module import is not a cross-test import."""
        path = _write(tmp_path, "tests/test_f.py", "from scripts.checks.hygiene import validate_placement\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []


class TestValidateNoCrossTestImportsFunction:
    """Exercises the registered check function itself (failed-list wiring)."""

    def test_appends_failed_on_violation(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_g.py", "from tests.test_foo import X\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_no_cross_test_imports(failed)
        assert failed == ["No-cross-test-import guard"]

    def test_real_tree_returns_clean(self) -> None:
        """The one pre-existing violation (tests/test_verifier_harness.py) is grandfathered,
        so the guard is clean over the real repo tests/ tree (unpatched ROOT)."""
        failed: list[str] = []
        validate_no_cross_test_imports(failed)
        assert failed == []
