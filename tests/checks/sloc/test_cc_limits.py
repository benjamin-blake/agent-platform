"""Tests for validate_cc_limits() -- Decision 43 cyclomatic-complexity gate."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.sloc.cc_limits import validate_cc_limits


class TestValidateCcLimits:
    """Tests for validate_cc_limits() -- Decision 43 cyclomatic-complexity gate."""

    def test_catches_over_limit_function(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Functions exceeding 20 branches without waiver are flagged by name."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        over_limit = scripts_dir / "big_func.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        over_limit.write_text(f"def heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert len(failed) == 1
        assert "Cyclomatic complexity" in failed[0]
        captured = capsys.readouterr()
        assert "heavy_dispatch" in captured.out

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Files with waiver annotation in first 10 lines are skipped entirely."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        waivered = scripts_dir / "waivered.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        waivered.write_text(
            f"# complexity-waiver: decision-43\ndef heavy_dispatch(x):\n{branches}\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []

    def test_allows_under_limit_function(self, tmp_path: Path) -> None:
        """Functions with 5 branches pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small = scripts_dir / "small_func.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(5))
        small.write_text(f"def light_func(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from CC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        init_file.write_text(f"def heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []
