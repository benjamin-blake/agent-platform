"""step_runner acceptance/scope/telemetry-append tests: run_acceptance, _enforce_step_scope,
_append_step_telemetry (rec-2709 Wave 5).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.executor.step_runner as sr_mod
from scripts.executor.step_runner import (
    _EXECUTOR_ACC_VARS,
    _append_step_telemetry,
    _enforce_step_scope,
    _list_meaningful_worktree_changes,
    commit_step,
    get_last_acceptance_output,
    run_acceptance,
)


class TestRunAcceptance:
    """Tests for run_acceptance()."""

    def test_returns_true_for_empty_string(self) -> None:
        assert run_acceptance("") is True

    def test_returns_true_for_whitespace_only(self) -> None:
        assert run_acceptance("   ") is True

    def test_returns_true_for_unparseable_nonempty_text(self) -> None:
        # Non-empty prose-only text (no shell command) is silently allowed for backwards
        # compatibility with existing step patterns. Prose-only acceptance fields skip validation.
        prose = "The function should exist in the module and return a value."
        result = run_acceptance(prose)
        assert result is True

    def test_returns_true_when_command_exits_zero(self) -> None:
        acc = "`echo hello`"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("hello\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_acceptance(acc)
        assert result is True

    def test_returns_false_when_command_exits_nonzero(self) -> None:
        acc = "`grep -q 'missing' file.py`"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("", "no match\n")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_acceptance(acc)
        assert result is False
        assert get_last_acceptance_output() == "no match"

    def test_normalises_bare_grep_q_to_case_insensitive(self) -> None:
        acc = "`grep -q 'missing' file.py`"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_args: list[list[str]] = []

        def capture_popen(args, **kwargs):
            captured_args.append(list(args))
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", side_effect=capture_popen):
            result = run_acceptance(acc)

        assert result is True
        assert captured_args[0][2] == "grep -qi 'missing' file.py"

    def test_leaves_non_grep_commands_unchanged(self) -> None:
        acc = "`echo hello`"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("hello\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_args: list[list[str]] = []

        def capture_popen(args, **kwargs):
            captured_args.append(list(args))
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", side_effect=capture_popen):
            result = run_acceptance(acc)

        assert result is True
        assert captured_args[0][2] == "echo hello"

    def test_returns_true_when_bash_not_found(self) -> None:
        acc = "`echo hello`"
        with patch("shutil.which", return_value=None):
            result = run_acceptance(acc)
        assert result is True

    def test_returns_false_on_timeout(self) -> None:
        acc = "`sleep 999`"
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=300)
        mock_proc.pid = 12345
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("shutil.which", return_value="/usr/bin/bash"),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("scripts.executor.step_runner.kill_process_tree"),
        ):
            result = run_acceptance(acc)
        assert result is False

    def test_normalises_python_script_to_module(self) -> None:
        """Verify python scripts/foo.py is normalised to python -m scripts.foo."""
        acc = "`python scripts/execute_recommendation.py --help`"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("help text\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_cmd: list[str] = []

        def capture_popen(args, **kwargs):
            captured_cmd.extend(args)
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", side_effect=capture_popen):
            run_acceptance(acc)

        # The bash -c argument should contain -m scripts.execute_recommendation
        bash_c_arg = captured_cmd[-1] if captured_cmd else ""
        assert "-m scripts.execute_recommendation" in bash_c_arg

    def test_rejects_python_c_one_liner(self) -> None:
        """python -c \"...\" acceptance commands are rejected to prevent Windows
        bash -c quoting failures. run_acceptance must return False without running
        the command."""
        acc = "`python -c \"import ast; ast.parse(open('f.py').read())\"`"
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_acceptance(acc)
        assert result is False
        mock_popen.assert_not_called()

    def test_rejects_python_c_with_single_quotes(self) -> None:
        """python -c 'code' is also rejected (same quoting issue)."""
        acc = "`python -c 'import sys; print(sys.version)'`"
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_acceptance(acc)
        assert result is False
        mock_popen.assert_not_called()

    def test_strips_executor_env_vars_from_acceptance(self) -> None:
        """Verify executor env vars (SKIP_CI_WAIT, etc.) are stripped from
        subprocess.Popen environment to prevent contaminating test execution."""
        acc = "`echo hello`"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("hello\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_env: dict | None = None

        def capture_popen(args, **kwargs):
            nonlocal captured_env
            captured_env = kwargs.get("env", {})
            return mock_proc

        with (
            patch.dict(
                "os.environ",
                {
                    "SKIP_CI_WAIT": "1",
                    "SKIP_CODE_REVIEW": "1",
                    "COPILOT_MODEL_EXECUTION": "gpt-5-mini",
                    "COPILOT_MODEL_PLANNING": "gpt-5.4",
                    "CI_FIX_RETRIES": "5",
                },
                clear=False,
            ),
            patch("shutil.which", return_value="/usr/bin/bash"),
            patch("subprocess.Popen", side_effect=capture_popen),
        ):
            result = run_acceptance(acc)

        assert result is True
        assert captured_env is not None
        for var in _EXECUTOR_ACC_VARS:
            assert var not in captured_env


class TestStepScopeEnforcement:
    """Tests for _enforce_step_scope() and _list_meaningful_worktree_changes()."""

    def _make_step(self, file: str = "src/module.py") -> dict:
        return {
            "n": 1,
            "title": "test step",
            "file": file,
            "action": "modify",
            "description": "",
            "acceptance": "",
        }

    def test_returns_true_when_no_file_declared(self) -> None:
        step = self._make_step(file="")
        assert _enforce_step_scope(step, 1) is True

    def test_returns_true_when_no_changes(self) -> None:
        with patch(
            "scripts.executor.step_runner._list_meaningful_worktree_changes",
            return_value=[],
        ):
            assert _enforce_step_scope(self._make_step(), 1) is True

    def test_returns_true_when_only_declared_file_changed(self) -> None:
        with patch(
            "scripts.executor.step_runner._list_meaningful_worktree_changes",
            return_value=["src/module.py"],
        ):
            assert _enforce_step_scope(self._make_step(), 1) is True

    def test_returns_true_when_declared_file_and_test_changed(self) -> None:
        with patch(
            "scripts.executor.step_runner._list_meaningful_worktree_changes",
            return_value=["src/module.py", "tests/test_module.py"],
        ):
            assert _enforce_step_scope(self._make_step(), 1) is True

    def test_returns_false_when_extra_file_changed(self) -> None:
        with patch(
            "scripts.executor.step_runner._list_meaningful_worktree_changes",
            return_value=["src/module.py", "src/other.py"],
        ):
            assert _enforce_step_scope(self._make_step(), 1) is False

    def test_normalises_backslash_paths(self) -> None:
        step = self._make_step(file="src\\module.py")
        with patch(
            "scripts.executor.step_runner._list_meaningful_worktree_changes",
            return_value=["src/module.py"],
        ):
            assert _enforce_step_scope(step, 1) is True

    def test_log_paths_are_ignored_by_meaningful_changes(self) -> None:
        """_list_meaningful_worktree_changes filters out logs/ prefixed paths."""
        git_diff = MagicMock(returncode=0, stdout="logs/debug/out.txt\n")
        git_cached = MagicMock(returncode=0, stdout="")
        git_ls = MagicMock(returncode=0, stdout="")
        with patch(
            "subprocess.run",
            side_effect=[git_diff, git_cached, git_ls],
        ):
            result = _list_meaningful_worktree_changes()
        assert result == []

    def test_meaningful_changes_includes_source_files(self) -> None:
        git_diff = MagicMock(returncode=0, stdout="src/module.py\n")
        git_cached = MagicMock(returncode=0, stdout="")
        git_ls = MagicMock(returncode=0, stdout="")
        with patch(
            "subprocess.run",
            side_effect=[git_diff, git_cached, git_ls],
        ):
            result = _list_meaningful_worktree_changes()
        assert result == ["src/module.py"]

    def test_commit_step_fails_when_scope_violated(self) -> None:
        """commit_step returns False when _enforce_step_scope fails."""
        with patch(
            "scripts.executor.step_runner._enforce_step_scope",
            return_value=False,
        ):
            ok, diff = commit_step(self._make_step(), "rec-001", 1)
        assert ok is False
        assert diff == ""


class TestAppendStepTelemetry:
    """Tests for _append_step_telemetry()."""

    def test_writes_json_entry(self, tmp_path: Path) -> None:
        telemetry = tmp_path / "telemetry.jsonl"
        with patch.object(sr_mod, "STEP_TELEMETRY_JSONL", telemetry):
            _append_step_telemetry(
                rec_id="rec-001",
                step_n=2,
                total_steps=5,
                prompt_hash="abc123",
                diff_stat="1 file changed",
                model="claude",
            )
        lines = telemetry.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["rec_id"] == "rec-001"
        assert entry["step_n"] == 2
        assert entry["prompt_hash"] == "abc123"
        assert entry["diff_stat"] == "1 file changed"

    def test_appends_multiple_entries(self, tmp_path: Path) -> None:
        telemetry = tmp_path / "telemetry.jsonl"
        with patch.object(sr_mod, "STEP_TELEMETRY_JSONL", telemetry):
            _append_step_telemetry("rec-001", 1, 3, "h1", "")
            _append_step_telemetry("rec-001", 2, 3, "h2", "")
        lines = telemetry.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_does_not_raise_on_io_error(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "nonexistent_dir" / "telemetry.jsonl"
        with patch.object(sr_mod, "STEP_TELEMETRY_JSONL", bad_path):
            _append_step_telemetry("rec-001", 1, 1, "h", "")  # must not raise
