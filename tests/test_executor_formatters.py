"""Unit tests for scripts/executor/formatters.py."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.formatters
from scripts.executor.formatters import (
    _run_ruff_fix,
    _run_ruff_format,
    auto_format_test_files,
)


class TestRunRuffFix:
    """Tests for _run_ruff_fix()."""

    def test_empty_list_returns_true(self) -> None:
        assert _run_ruff_fix([]) is True

    def test_no_python_files_returns_true(self) -> None:
        assert _run_ruff_fix(["README.md", "config.yaml"]) is True

    def test_nonexistent_file_returns_true(self) -> None:
        assert _run_ruff_fix(["nonexistent.py"]) is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    @patch("scripts.executor.formatters.shutil.which", return_value="/usr/bin/ruff")
    def test_exit_0_returns_true(self, mock_which: MagicMock, mock_popen: MagicMock, tmp_path: Path) -> None:
        py_file = tmp_path / "test_example.py"
        py_file.write_text("x = 1\n")
        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc
        assert _run_ruff_fix([str(py_file)]) is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    @patch("scripts.executor.formatters.shutil.which", return_value="/usr/bin/ruff")
    def test_exit_2_returns_false(self, mock_which: MagicMock, mock_popen: MagicMock, tmp_path: Path) -> None:
        py_file = tmp_path / "test_example.py"
        py_file.write_text("x = 1\n")
        proc = MagicMock()
        proc.communicate.return_value = ("", "ruff error")
        proc.returncode = 2
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc
        assert _run_ruff_fix([str(py_file)]) is False

    @patch("scripts.executor.formatters.kill_process_tree")
    @patch("scripts.executor.formatters.subprocess.Popen")
    @patch("scripts.executor.formatters.shutil.which", return_value="/usr/bin/ruff")
    def test_timeout_returns_false(
        self, mock_which: MagicMock, mock_popen: MagicMock, mock_kill: MagicMock, tmp_path: Path
    ) -> None:
        py_file = tmp_path / "test_example.py"
        py_file.write_text("x = 1\n")
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="ruff", timeout=30)
        proc.pid = 12345
        proc.returncode = -1
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc
        assert _run_ruff_fix([str(py_file)]) is False
        mock_kill.assert_called_once_with(12345)


class TestRunRuffFormat:
    """Tests for _run_ruff_format()."""

    def test_empty_list_returns_true(self) -> None:
        assert _run_ruff_format([]) is True

    def test_no_python_files_returns_true(self) -> None:
        assert _run_ruff_format(["README.md"]) is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    def test_success_returns_true(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        py_file = tmp_path / "example.py"
        py_file.write_text("x = 1\n")
        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc
        assert _run_ruff_format([str(py_file)]) is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    def test_failure_returns_false(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        py_file = tmp_path / "example.py"
        py_file.write_text("x = 1\n")
        proc = MagicMock()
        proc.communicate.return_value = ("", "format error")
        proc.returncode = 1
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc
        assert _run_ruff_format([str(py_file)]) is False


class TestAutoFormatTestFiles:
    """Tests for auto_format_test_files()."""

    def test_empty_step_file_returns_true(self) -> None:
        assert auto_format_test_files("") is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    def test_formats_existing_test_file(self, mock_popen: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("x = 1\n")
        src_file = tmp_path / "scripts" / "example.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("x = 1\n")

        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc

        result = auto_format_test_files("scripts/example.py")
        assert result is True

    @patch("scripts.executor.formatters.subprocess.Popen")
    def test_handles_test_file_as_step_file(
        self, mock_popen: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_widget.py"
        test_file.write_text("x = 1\n")

        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = proc

        result = auto_format_test_files("tests/test_widget.py")
        assert result is True


class TestVenvPythonResolution:
    """Verify Linux-first venv resolution in formatters.py module-level globals."""

    @pytest.fixture(autouse=True)
    def _restore_module_state(self) -> None:
        importlib.reload(scripts.executor.formatters)
        yield
        importlib.reload(scripts.executor.formatters)

    def test_linux_layout_preferred_when_both_present(self) -> None:
        with patch.object(Path, "exists", return_value=True):
            importlib.reload(scripts.executor.formatters)
        assert scripts.executor.formatters._PROJECT_PYTHON.endswith("bin/python")

    def test_windows_fallback_when_linux_missing(self) -> None:
        def _exists(self: Path) -> bool:
            return "python.exe" in str(self) or "ruff.exe" in str(self)

        with patch.object(Path, "exists", _exists):
            importlib.reload(scripts.executor.formatters)
        assert "python.exe" in scripts.executor.formatters._PROJECT_PYTHON

    def test_ruff_resolution_linux_first(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("x = 1\n")

        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        proc.__enter__ = MagicMock(return_value=proc)
        proc.__exit__ = MagicMock(return_value=False)

        with patch("scripts.executor.formatters.subprocess.Popen", return_value=proc) as mock_popen:
            with patch.object(Path, "exists", return_value=True):
                result = auto_format_test_files("tests/test_example.py")
        assert result is True
        assert mock_popen.called, "Popen was never called -- ruff_cmd_prefix was not constructed"
        cmd = mock_popen.call_args[0][0]
        assert cmd[0].endswith("bin/ruff")
