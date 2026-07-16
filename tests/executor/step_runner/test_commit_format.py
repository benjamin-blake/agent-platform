"""step_runner commit / auto-format / ruff / debug-output tests: commit_step,
auto_format_test_files, _run_ruff_fix, _run_ruff_format (rec-2709 Wave 5).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.executor.step_runner import (
    StepOutcome,
    _run_ruff_fix,
    _run_ruff_format,
    auto_format_test_files,
    commit_step,
    implement_step,
)


class TestCommitStep:
    """Tests for commit_step()."""

    def _make_step(self, title: str = "do something") -> dict:
        return {"n": 1, "title": title, "file": "f.py", "action": "modify", "description": "", "acceptance": ""}

    def test_returns_true_on_success(self) -> None:
        mock_add = MagicMock(returncode=0)
        mock_commit = MagicMock(returncode=0, stderr="", stdout="1 file changed")
        mock_diff = MagicMock(returncode=0, stdout="f.py | 2 ++")

        with (
            patch("scripts.executor.step_runner._enforce_step_scope", return_value=True),
            patch("subprocess.run", side_effect=[mock_add, mock_commit, mock_diff]),
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)
        assert ok is True
        assert "f.py" in diff

    def test_returns_true_on_nothing_to_commit(self) -> None:
        mock_add = MagicMock(returncode=0)
        err = subprocess.CalledProcessError(1, "git commit")
        err.stderr = "nothing to commit, working tree clean"
        err.stdout = ""

        with (
            patch("scripts.executor.step_runner._enforce_step_scope", return_value=True),
            patch("subprocess.run", side_effect=[mock_add, err]),
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)
        assert ok is True
        assert diff == ""

    def test_retries_after_precommit_hook_modification(self) -> None:
        """Pre-commit hooks modify files -> retry up to 3 times."""
        mock_add = MagicMock(returncode=0)
        hook_err = subprocess.CalledProcessError(1, "git commit")
        hook_err.stderr = "files were modified by this hook -- please re-add them"
        hook_err.stdout = ""
        mock_commit_ok = MagicMock(returncode=0, stderr="", stdout="1 file changed")
        mock_diff = MagicMock(returncode=0, stdout="f.py | 1 +")

        with (
            patch("scripts.executor.step_runner._enforce_step_scope", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    mock_add,
                    hook_err,  # attempt 1: hook fails
                    mock_add,
                    mock_commit_ok,  # attempt 2: success
                    mock_diff,
                ],
            ),
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)
        assert ok is True

    def test_returns_false_on_unexpected_commit_error(self) -> None:
        mock_add = MagicMock(returncode=0)
        err = subprocess.CalledProcessError(128, "git commit")
        err.stderr = "fatal: not a git repository"
        err.stdout = ""

        with (
            patch("scripts.executor.step_runner._enforce_step_scope", return_value=True),
            patch("subprocess.run", side_effect=[mock_add, err, mock_add, err, mock_add, err]),
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)
        assert ok is False

    def test_adds_no_verify_flag_on_final_commit_attempt(self) -> None:
        """Final retry (attempt 3) adds --no-verify to bypass pre-commit hooks."""
        mock_add = MagicMock(returncode=0)
        hook_err = subprocess.CalledProcessError(1, "git commit")
        hook_err.stderr = "files were modified by this hook -- please re-add them"
        hook_err.stdout = ""
        mock_commit_ok = MagicMock(returncode=0, stderr="", stdout="1 file changed")
        mock_diff = MagicMock(returncode=0, stdout="f.py | 1 +")

        calls: list = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0:2] == ["git", "commit"]:
                attempt_num = sum(1 for c in calls if c[0:2] == ["git", "commit"])
                if attempt_num <= 2:
                    raise hook_err
                elif attempt_num == 3:
                    if "--no-verify" not in cmd:
                        raise AssertionError("Expected --no-verify flag on attempt 3")
                    return mock_commit_ok
            elif cmd[0:2] == ["git", "diff"]:
                return mock_diff
            elif cmd[0:2] == ["git", "add"]:
                return mock_add

        with (
            patch("scripts.executor.step_runner._enforce_step_scope", return_value=True),
            patch("subprocess.run", side_effect=mock_run),
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)

        assert ok is True
        commit_calls = [c for c in calls if c[0:2] == ["git", "commit"]]
        assert len(commit_calls) == 3
        assert "--no-verify" in commit_calls[2]


class TestAutoFormatTestFiles:
    """Tests for auto_format_test_files()."""

    def test_returns_true_for_empty_step_file(self) -> None:
        """Returns True immediately if step_file is empty."""
        result = auto_format_test_files("")
        assert result is True

    def test_returns_true_when_no_test_file_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns True when no corresponding test file exists."""
        monkeypatch.chdir(tmp_path)
        step_file = "src/mymodule.py"
        result = auto_format_test_files(step_file)
        assert result is True

    def test_formats_existing_test_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calls ruff format on existing test file."""
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_mymodule.py"
        test_file.write_text("def test_foo( ):  pass\n", encoding="utf-8")

        step_file = "src/mymodule.py"

        # Mock subprocess to capture ruff format call
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            result = auto_format_test_files(step_file)

        assert result is True

    def test_returns_true_on_ruff_format_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Format failure is non-fatal — returns True and logs a warning."""
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_mymodule.py"
        test_file.write_text("def test_foo(): pass\n", encoding="utf-8")

        step_file = "src/mymodule.py"

        # Mock subprocess to return nonzero exit code
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("", "ruff format error")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            result = auto_format_test_files(step_file)

        # Format failures are non-fatal: correctness is enforced by validate.py
        assert result is True

    def test_returns_true_on_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Timeout during format is non-fatal — returns True and logs a warning."""
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_mymodule.py"
        test_file.write_text("def test_foo(): pass\n", encoding="utf-8")

        step_file = "src/mymodule.py"

        # Mock subprocess to raise TimeoutExpired
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="ruff format", timeout=30)
        mock_proc.pid = 12345
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("scripts.executor.step_runner.kill_process_tree"),
        ):
            result = auto_format_test_files(step_file)

        # Timeout during format is non-fatal: step continues
        assert result is True

    def test_discovers_secondary_test_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovers and formats secondary test files created recently in tests/."""
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # Create primary test file
        test_file1 = tests_dir / "test_mymodule.py"
        test_file1.write_text("def test_foo(): pass\n", encoding="utf-8")

        # Create secondary test file (modified recently)
        test_file2 = tests_dir / "test_mymodule_integration.py"
        test_file2.write_text("def test_integration( ): pass\n", encoding="utf-8")

        step_file = "src/mymodule.py"

        # Track which files were formatted
        formatted_files: list[str] = []

        def capture_popen(args, **kwargs):
            # args is either [ruff_binary, "format", filepath] (shutil.which path)
            # or [sys.executable, "-m", "ruff", "format", filepath] (fallback)
            if "format" in args:
                fmt_idx = list(args).index("format")
                if fmt_idx + 1 < len(args):
                    formatted_files.append(args[fmt_idx + 1])
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            mock_proc.__enter__ = lambda self: self
            mock_proc.__exit__ = MagicMock(return_value=False)
            return mock_proc

        with patch("subprocess.Popen", side_effect=capture_popen):
            result = auto_format_test_files(step_file)

        assert result is True
        # Both test files should have been formatted
        assert any("test_mymodule.py" in f for f in formatted_files)
        assert any("test_mymodule_integration.py" in f for f in formatted_files)

    def test_formats_step_file_when_it_is_itself_a_test_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When step_file IS a test file (e.g. tests/test_validate.py), format it directly.

        Regression: previously the stem 'test_validate' caused a lookup for
        'tests/test_test_validate.py' (double-prefixed), missing the actual file.
        """
        monkeypatch.chdir(tmp_path)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_validate.py"
        test_file.write_text("def test_example( ):  pass\n", encoding="utf-8")

        step_file = "tests/test_validate.py"

        formatted_files: list[str] = []

        def capture_popen(args, **kwargs):
            if "format" in args:
                fmt_idx = list(args).index("format")
                if fmt_idx + 1 < len(args):
                    formatted_files.append(args[fmt_idx + 1])
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            mock_proc.__enter__ = lambda self: self
            mock_proc.__exit__ = MagicMock(return_value=False)
            return mock_proc

        with patch("subprocess.Popen", side_effect=capture_popen):
            result = auto_format_test_files(step_file)

        assert result is True
        assert any("test_validate.py" in f for f in formatted_files), (
            f"Expected test_validate.py to be formatted, got: {formatted_files}"
        )


class TestRunRuffFix:
    """Tests for _run_ruff_fix()."""

    def test_returns_true_for_empty_list(self) -> None:
        assert _run_ruff_fix([]) is True

    def test_returns_true_for_non_python_files(self) -> None:
        assert _run_ruff_fix(["README.md", "config.yaml"]) is True

    def test_skips_nonexistent_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert _run_ruff_fix(["nonexistent.py"]) is True

    def test_runs_ruff_check_fix_on_python_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "myfile.py"
        py_file.write_text("pass\n", encoding="utf-8")

        captured_args: list[list] = []
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        def capture(args, **kw):
            captured_args.append(list(args))
            return mock_proc

        with patch("subprocess.Popen", side_effect=capture):
            result = _run_ruff_fix([str(py_file)])

        assert result is True
        assert len(captured_args) == 1
        # First element is either the ruff binary path or sys.executable;
        # either way the literal "--fix" flag must be present.
        assert any("ruff" in str(arg) for arg in captured_args[0])
        assert "--fix" in captured_args[0]

    def test_returns_true_on_exit_code_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exit code 1 means issues found (some fixed) -- not an error."""
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "myfile.py"
        py_file.write_text("pass\n", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("Fixed 1 error", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            assert _run_ruff_fix([str(py_file)]) is True

    def test_returns_false_on_exit_code_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exit code 2 means ruff itself errored."""
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "myfile.py"
        py_file.write_text("pass\n", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.communicate.return_value = ("", "ruff error")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            assert _run_ruff_fix([str(py_file)]) is False

    def test_returns_false_on_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "myfile.py"
        py_file.write_text("pass\n", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="ruff", timeout=30)
        mock_proc.pid = 99999
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("scripts.executor.step_runner.kill_process_tree"),
        ):
            assert _run_ruff_fix([str(py_file)]) is False


class TestRunRuffFormat:
    """Tests for _run_ruff_format()."""

    def test_returns_true_for_empty_list(self) -> None:
        assert _run_ruff_format([]) is True

    def test_runs_ruff_format_on_python_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "myfile.py"
        py_file.write_text("pass\n", encoding="utf-8")

        captured_args: list[list] = []
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        def capture(args, **kw):
            captured_args.append(list(args))
            return mock_proc

        with patch("subprocess.Popen", side_effect=capture):
            result = _run_ruff_format([str(py_file)])

        assert result is True
        assert len(captured_args) == 1
        assert any("ruff" in str(arg) for arg in captured_args[0])
        assert "format" in captured_args[0]


class TestValidateDebugOutput:
    """Tests that implement_step writes validate failure output to logs/debug/."""

    def test_validate_failure_writes_debug_file(self, tmp_path: pytest.MonkeyPatch) -> None:
        """When validate.py returns non-zero, a debug file is written to logs/debug/."""
        (tmp_path / "logs" / "debug").mkdir(parents=True)
        step = {
            "n": 1,
            "action": "modify",
            "file": "scripts/foo.py",
            "title": "test step",
            "prompt": "Do something.",
            "acceptance": "",
        }
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = "reformed code\n"

        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.session_id = "sess-1"

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("FAILED: ruff\nFailed checks: foo\n", "")
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "scripts.executor.step_runner.gather_step_context",
                return_value={"file_content": "ctx", "test_content": "", "pattern_content": ""},
            ),
            patch("scripts.executor.step_runner.load_prompt", return_value=("implement step", "abc123")),
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner._detect_ghost_step", return_value=False),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner.build_context_path", return_value=str(tmp_path / "t.md")),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            # Redirect debug writes into tmp_path
            import os

            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                result = implement_step(step, "rec-test", 1, 1)
            finally:
                os.chdir(orig_cwd)

        success, _, _, _ = result
        assert success == StepOutcome.VALIDATE_FAILED
        # Verify at least one debug file was created in the temp logs/debug dir
        debug_files = list((tmp_path / "logs" / "debug").glob("validate-rec-test-step1-*.txt"))
        assert len(debug_files) == 1
        assert "FAILED" in debug_files[0].read_text(encoding="utf-8")
