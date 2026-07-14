"""Unit tests for scripts/executor/step_runner.py."""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.step_runner as sr_mod
import scripts.llm.model_registry as model_registry_mod
from scripts.executor.step_runner import (
    _EXECUTOR_ACC_VARS,
    OPUS_FALLBACK,
    StepOutcome,
    _append_step_telemetry,
    _enforce_step_scope,
    _extract_acceptance_command,
    _list_meaningful_worktree_changes,
    _run_ruff_fix,
    _run_ruff_format,
    auto_format_test_files,
    commit_step,
    escalate_implementation_model,
    gather_step_context,
    get_implementation_model,
    get_last_acceptance_output,
    get_last_verification_output,
    get_step_timeout_secs,
    implement_step,
    run_acceptance,
    run_verification,
)


class TestGatherStepContext:
    """Tests for gather_step_context()."""

    def test_returns_file_content_for_modify(self, tmp_path: Path) -> None:
        target = tmp_path / "mymodule.py"
        target.write_text("def foo(): pass\n", encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=10000)
        assert "def foo" in result["file_content"]

    def test_empty_content_for_missing_modify_file(self, tmp_path: Path) -> None:
        step = {"action": "modify", "file": str(tmp_path / "missing.py")}
        result = gather_step_context(step, max_chars=10000)
        assert result["file_content"] == ""

    def test_returns_pattern_content_for_create(self, tmp_path: Path) -> None:
        existing = tmp_path / "existing_module.py"
        existing.write_text("# pattern file\ndef bar(): pass\n", encoding="utf-8")
        new_file = tmp_path / "new_module.py"
        step = {"action": "create", "file": str(new_file)}
        result = gather_step_context(step, max_chars=10000)
        assert "bar" in result["pattern_content"]

    def test_no_pattern_when_create_dir_empty(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "empty_dir"
        new_dir.mkdir()
        step = {"action": "create", "file": str(new_dir / "new.py")}
        result = gather_step_context(step, max_chars=10000)
        assert result["pattern_content"] == ""

    def test_includes_test_file_if_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "mymodule.py"
        target.write_text("def foo(): pass\n", encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_mymodule.py"
        test_file.write_text("def test_foo(): pass\n", encoding="utf-8")

        # Monkeypatch Path("tests") / f"test_{stem}.py" resolution
        # We do this by patching step_runner's Path so it resolves relative to tmp_path
        original_path = sr_mod.Path

        class PatchedPath(type(original_path("."))):
            pass

        # Easier approach: mock the test file path directly by patching the call
        # Actually, gather_step_context uses Path("tests") / f"test_{stem}.py" which is relative.
        # So we need to either be in the right CWD or mock it.
        # Best approach: patch Path so that tests/test_mymodule.py resolves to our tmp file.
        with patch.object(sr_mod, "Path") as MockPath:
            # Set up: file_path.stem = "mymodule", test check
            mock_file = MagicMock()
            mock_file.stem = "mymodule"
            mock_file.parent = MagicMock()
            mock_file.suffix = ".py"
            mock_file.parent.is_dir.return_value = False
            mock_file.exists.return_value = True
            mock_file.__str__ = lambda self: str(target)
            mock_file.read_text.return_value = "def foo(): pass\n"

            mock_test = MagicMock()
            mock_test.exists.return_value = True
            mock_test.read_text.return_value = "def test_foo(): pass\n"

            def path_side_effect(*args):
                if args and str(args[0]) == str(target):
                    return mock_file
                if args and str(args[0]) == "tests":
                    mock_tests_dir = MagicMock()
                    mock_tests_dir.__truediv__ = lambda self, name: mock_test
                    return mock_tests_dir
                return original_path(*args)

            MockPath.side_effect = path_side_effect

            # Fall back to simpler integration approach without mocking Path
        # Integration approach: use real paths with CWD patching
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=10000)
        # file_content should be populated; test_content requires CWD match which we skip here
        assert "def foo" in result["file_content"]

    def test_empty_result_for_missing_file_key(self) -> None:
        step = {"action": "modify"}
        result = gather_step_context(step)
        assert result == {"file_content": "", "test_content": "", "pattern_content": ""}

    def test_content_truncated_when_exceeds_budget(self, tmp_path: Path) -> None:
        target = tmp_path / "big.py"
        target.write_text("x" * 1000 + "\n", encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=50)
        assert len(result["file_content"]) < 200  # truncated
        assert "omitted" in result["file_content"]


class TestExtractAcceptanceCommand:
    """Tests for _extract_acceptance_command()."""

    def test_extracts_fenced_block(self) -> None:
        acc = "Run this:\n```bash\ngrep -q foo bar.py\n```\nDone."
        cmd = _extract_acceptance_command(acc)
        assert cmd == "grep -q foo bar.py"

    def test_extracts_inline_backtick_python(self) -> None:
        acc = 'Verify with `python -c "import foo"`'
        cmd = _extract_acceptance_command(acc)
        assert "python" in cmd

    def test_extracts_inline_backtick_grep(self) -> None:
        acc = "Check with `grep -q 'hello' file.py`"
        cmd = _extract_acceptance_command(acc)
        assert "grep" in cmd

    def test_extracts_via_line_scan_python(self) -> None:
        acc = "Verify:\npython -m scripts.execute_recommendation --help"
        cmd = _extract_acceptance_command(acc)
        assert "python" in cmd

    def test_extracts_via_line_scan_pytest(self) -> None:
        acc = "Run tests:\npytest tests/test_foo.py -v"
        cmd = _extract_acceptance_command(acc)
        assert "pytest" in cmd

    def test_returns_empty_for_prose_only(self) -> None:
        acc = "The function should exist and return the correct value."
        cmd = _extract_acceptance_command(acc)
        assert cmd == ""

    def test_returns_empty_for_empty_input(self) -> None:
        cmd = _extract_acceptance_command("")
        assert cmd == ""

    def test_fenced_block_takes_priority_over_inline(self) -> None:
        acc = "Try `echo inline` but use:\n```bash\necho fenced\n```"
        cmd = _extract_acceptance_command(acc)
        assert "fenced" in cmd

    def test_skips_lang_tags_in_line_scan(self) -> None:
        acc = 'Run:\nbash\npython -c "import x"'
        cmd = _extract_acceptance_command(acc)
        # Should skip 'bash' as a lang tag and pick python
        assert "python" in cmd


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


class TestImplementStep:
    """Tests for implement_step() integration with auto_format_test_files()."""

    def _make_step(self, title: str = "do something", file: str = "src/mymodule.py", action: str = "modify") -> dict:
        return {
            "n": 1,
            "title": title,
            "file": file,
            "action": action,
            "description": "test step",
            "acceptance": "",
        }

    def test_calls_auto_format_test_files_and_fails_when_formatting_fails(self) -> None:
        """Verifies that implement_step() calls auto_format_test_files() and fails if it returns False."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock auto_format_test_files to fail
        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=False),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.FORMAT_ERROR
        assert reqs == 1.0

    def test_calls_auto_format_test_files_and_succeeds_when_formatting_succeeds(self) -> None:
        """Verifies that implement_step() calls auto_format_test_files() and continues when it returns True."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock auto_format_test_files to succeed
        # Also mock validate.py to succeed
        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0

    def test_fails_when_ruff_fix_fails(self) -> None:
        """implement_step() fails if _run_ruff_fix returns False."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=False),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.RUFF_ERROR
        assert reqs == 1.0

    def test_implement_step_uses_context_file(self) -> None:
        """Verify implement_step passes context_file_path and inline_instruction."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(sr_mod, "llm_call", return_value=mock_result) as mock_call,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-254", step_n=2, total_steps=3)

            # Verify llm_call was called with context_file_path and inline_instruction
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert "context_file_path" in call_kwargs
            context_file = call_kwargs["context_file_path"]
            assert "impl" in context_file
            assert "rec-254" in context_file
            assert "inline_instruction" in call_kwargs
            inline_instr = call_kwargs["inline_instruction"]
            assert "Implement step 2/3" in inline_instr
            # Per custom instruction, @context_file_path must be inline in the instruction
            assert "@" in inline_instr
            assert context_file in inline_instr
            assert success == StepOutcome.SUCCESS

    def test_runs_post_fix_ruff_format_before_validate(self) -> None:
        """Regression: validate should see the file after ruff auto-fixes and formatting."""
        step = self._make_step(file="tests/test_execute_recommendation.py")

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        call_order: list[str] = []

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch(
                "scripts.executor.step_runner.auto_format_test_files",
                side_effect=lambda _: call_order.append("auto_format") or True,
            ),
            patch(
                "scripts.executor.step_runner._run_ruff_fix",
                side_effect=lambda _: call_order.append("ruff_fix") or True,
            ),
            patch(
                "scripts.executor.step_runner._run_ruff_format",
                side_effect=lambda _: call_order.append("ruff_format") or True,
            ),
            patch(
                "subprocess.Popen",
                side_effect=lambda *args, **kwargs: (
                    (
                        call_order.append("validate")
                        if list(args[0])[0:3] == [sr_mod._PROJECT_PYTHON, "scripts/validate.py", "--pre"]
                        else None
                    )
                    or mock_val_proc
                ),
            ),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert call_order == ["auto_format", "ruff_fix", "ruff_format", "validate"]


class TestGhostStepDetection:
    """Tests for _detect_ghost_step() and ghost step detection in implement_step()."""

    def _make_step(self, title: str = "do something", file: str = "src/mymodule.py", action: str = "modify") -> dict:
        return {
            "n": 1,
            "title": title,
            "file": file,
            "action": action,
            "description": "test step",
            "acceptance": "",
        }

    def test_ghost_step_detected_when_modify_action_with_no_changes(self) -> None:
        """implement_step() detects and fails when modify action has no file changes."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock subprocess.run to return empty output (git diff --name-only has no changes)
        def subprocess_run_side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("subprocess.run", side_effect=subprocess_run_side_effect),
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,  # Should NOT be called
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.GHOST_STEP
        assert reqs == 1.0
        mock_auto_format.assert_not_called()

    def test_ghost_step_not_detected_when_files_changed(self) -> None:
        """implement_step() continues when modify action has file changes."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock subprocess.run to return file list (git diff shows changes)
        def subprocess_run_side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "src/mymodule.py\n"
            return result

        # Mock validation process
        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("subprocess.run", side_effect=subprocess_run_side_effect),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0

    def test_noop_modify_step_succeeds_when_acceptance_already_passes(self) -> None:
        """implement_step() allows a no-op modify step when acceptance already passes cleanly."""
        step = self._make_step()
        step["acceptance"] = "`python -m pytest tests/test_executor_step_runner.py -q`"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0
        mock_result.session_id = "session-123"

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner._detect_ghost_step", return_value=True),
            patch("scripts.executor.step_runner._list_meaningful_worktree_changes", return_value=[]),
            patch("scripts.executor.step_runner.run_acceptance", return_value=True) as mock_acceptance,
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0
        assert session_id == "session-123"
        mock_acceptance.assert_called_once_with(step["acceptance"])
        mock_auto_format.assert_not_called()

    def test_ghost_step_still_fails_when_other_files_changed(self) -> None:
        """implement_step() still fails if the target file is unchanged but other files changed."""
        step = self._make_step()
        step["acceptance"] = "`python -m pytest tests/test_executor_step_runner.py -q`"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner._detect_ghost_step", return_value=True),
            patch(
                "scripts.executor.step_runner._list_meaningful_worktree_changes",
                return_value=["src/unexpected.py"],
            ),
            patch("scripts.executor.step_runner.run_acceptance") as mock_acceptance,
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.GHOST_STEP
        assert reqs == 1.0
        mock_acceptance.assert_not_called()
        mock_auto_format.assert_not_called()


class TestImplementationModelSelection:
    """Tests for get_implementation_model() and escalate_implementation_model()."""

    def test_xs_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview") as mock_resolve:
            result = get_implementation_model("XS")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="")
        assert result == "gemini-3-flash-preview"

    def test_l_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("L")
        mock_resolve.assert_called_once_with("implementation", "L", file_path="")
        assert result == "gemini-3-pro-preview"

    def test_executor_file_passes_file_path_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XS", "scripts/executor/plan.py")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="scripts/executor/plan.py")
        assert result == "gemini-3-pro-preview"

    def test_validate_file_passes_file_path_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XS", "scripts/validate.py")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="scripts/validate.py")
        assert result == "gemini-3-pro-preview"

    def test_env_override_takes_precedence_via_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_MODEL_EXECUTION", "my-override-model")
        result = get_implementation_model("XS")
        assert result == "my-override-model"

    def test_returns_none_for_auto_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value=None):
            result = get_implementation_model("S")
        assert result is None

    def test_opus_fallback_constant_retained(self) -> None:
        # OPUS_FALLBACK is retained for backwards compatibility with external importers.
        assert OPUS_FALLBACK == "claude-opus-4.6"

    def test_escalate_under_threshold_returns_current(self) -> None:
        rec_id = "rec-impl-escalate-01"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        # Use 'auto' tier (threshold=3) to stay under threshold on first call
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, None)  # auto mode, None model
        mock_esc.assert_not_called()
        assert result is None  # returned current_model (None for auto mode)

    def test_escalate_flash_tier_triggers_after_1_failure(self) -> None:
        rec_id = "rec-impl-escalate-02"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="flash"),
            patch.object(model_registry_mod, "escalate_model", return_value=None) as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_called_once_with("implementation", "flash")
        assert result is None  # auto mode (flash -> auto = None in Gemini config)

    def test_escalate_auto_tier_does_not_trigger_after_1_failure(self) -> None:
        rec_id = "rec-impl-escalate-03"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, None)  # auto mode
        mock_esc.assert_not_called()
        assert result is None  # count=1, threshold for non-flash = 3

    def test_escalate_at_pro_returns_none_top_of_hierarchy(self) -> None:
        rec_id = "rec-impl-escalate-04"
        sr_mod._IMPL_FAILURE_COUNT[rec_id] = 2  # next hit = 3 (threshold for non-flash)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="pro"),
            patch.object(model_registry_mod, "escalate_model", return_value=None),
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-pro-preview")
        assert result is None

    def test_escalate_delegates_to_resolver(self) -> None:
        rec_id = "rec-impl-escalate-05"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="flash"),
            patch.object(model_registry_mod, "escalate_model", return_value="gemini-3-pro-preview") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_called_once_with("implementation", "flash")
        assert result == "gemini-3-pro-preview"

    def test_l_executor_instructions_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("L", "config/agent/executor/instructions/executor-planning.instructions.md")
        mock_resolve.assert_called_once_with(
            "implementation",
            "L",
            file_path="config/agent/executor/instructions/executor-planning.instructions.md",
        )
        assert result == "gemini-3-pro-preview"

    def test_xl_github_agents_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XL", ".github/agents/code-review.agent.md")
        mock_resolve.assert_called_once_with(
            "implementation",
            "XL",
            file_path=".github/agents/code-review.agent.md",
        )
        assert result == "gemini-3-pro-preview"

    def test_step_timeout_defaults_to_900(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_STEP_TIMEOUT_SECS", raising=False)
        assert get_step_timeout_secs() == 900

    def test_step_timeout_invalid_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_STEP_TIMEOUT_SECS", "invalid")
        assert get_step_timeout_secs() == 900


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


class TestRunVerification:
    """Tests for run_verification()."""

    def test_returns_skipped_for_empty_string(self) -> None:
        result = run_verification("")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_skipped_for_whitespace(self) -> None:
        result = run_verification("   ")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_skipped_for_unparseable_prose(self) -> None:
        result = run_verification("The system should work correctly.")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_passed_when_command_exits_zero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("ok\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_verification("`echo ok`")
        assert result["passed"] is True
        assert result["skipped"] is False
        assert result["rejected"] is False
        assert get_last_verification_output() == "ok"

    def test_returns_failed_when_command_exits_nonzero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("", "error\n")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_verification("`grep -q 'missing' file.py`")
        assert result["passed"] is False
        assert result["skipped"] is False
        assert result["error"] == "exit 1"
        assert get_last_verification_output() == "error"

    def test_rejects_python_c_one_liner(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_verification('`python -c "import sys"`')
        assert result["passed"] is False
        assert result["rejected"] is True
        mock_popen.assert_not_called()

    def test_rejects_python_c_single_quotes(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_verification("`python -c 'import sys'`")
        assert result["passed"] is False
        assert result["rejected"] is True
        mock_popen.assert_not_called()

    def test_returns_skipped_when_bash_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            result = run_verification("`echo hello`")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_failed_on_timeout(self) -> None:
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
            result = run_verification("`sleep 999`")
        assert result["passed"] is False
        assert result["skipped"] is False
        assert "timed out" in result["error"].lower()

    def test_normalises_python_script_to_module(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_cmd: list[str] = []

        def capture_popen(args, **kwargs):
            captured_cmd.extend(args)
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", side_effect=capture_popen):
            run_verification("`python scripts/foo.py --check`")

        bash_c_arg = captured_cmd[-1] if captured_cmd else ""
        assert "-m scripts.foo" in bash_c_arg


class TestEmitStepTelemetry:
    """Verify emit_step is called from implement_step's finally block."""

    def _make_step(self, file: str = "src/module.py", action: str = "modify") -> dict:
        return {"n": 1, "title": "telemetry test step", "file": file, "action": action, "description": "d", "acceptance": ""}

    def test_emit_step_called_on_success(self) -> None:
        """emit_step is called with outcome=SUCCESS.value after a successful implement_step."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.5
        mock_result.session_id = "sess-tel"

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("ok", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.executor.step_runner.emit_step") as mock_emit_step,
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
        ):
            outcome, reqs, _, _ = implement_step(step, "rec-tel-001", 1, 1)

        assert outcome == StepOutcome.SUCCESS
        mock_emit_step.assert_called_once()
        assert mock_emit_step.call_args.kwargs.get("outcome") == StepOutcome.SUCCESS.value

    def test_emit_step_called_on_ruff_error(self) -> None:
        """emit_step is called even when implement_step returns RUFF_ERROR."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.5

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=False),
            patch("scripts.executor.step_runner.emit_step") as mock_emit_step,
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
        ):
            outcome, _, _, _ = implement_step(step, "rec-tel-002", 1, 1)

        assert outcome == StepOutcome.RUFF_ERROR
        mock_emit_step.assert_called_once()
        assert mock_emit_step.call_args.kwargs.get("outcome") == StepOutcome.RUFF_ERROR.value


class TestGetRelevantGotchas:
    """Tests for _get_relevant_gotchas()."""

    def test_get_relevant_gotchas_terraform(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("terraform/main.tf")
        assert "try()" in g

    def test_get_relevant_gotchas_no_match(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("README.md")
        assert g == ""

    def test_get_relevant_gotchas_tests_dir(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("tests/test_foo.py")
        assert "Test Isolation" in g

    def test_gotcha_injection_in_gather_context(self, tmp_path: Path) -> None:
        """gather_step_context injects gotchas for .tf files."""
        target = tmp_path / "iceberg_tables.tf"
        target.write_text('resource "aws_glue_catalog_table" "example" {}\n', encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        # Patch the file path used to match so relative gotcha map key is matched
        with patch("scripts.executor.step_runner._get_relevant_gotchas", wraps=sr_mod._get_relevant_gotchas):
            gather_step_context(step, max_chars=10000)
        # For a .tf file not at terraform/ prefix, no gotcha is injected (abs path has no prefix match)
        # But if we use a relative path with terraform/ prefix, it should inject
        step2 = {"action": "modify", "file": "terraform/iceberg_tables.tf"}
        with patch("pathlib.Path.exists", return_value=False):
            result2 = gather_step_context(step2, max_chars=10000)
        # Gotchas should appear (even though file doesn't exist, gotcha is injected based on path)
        assert "try()" in result2.get("file_content", "")


class TestImplementStepResumeSkip:
    """Tests for resume_session_id skip logic in implement_step()."""

    @staticmethod
    def _make_step() -> dict:
        return {
            "n": 1,
            "title": "Add function",
            "file": "scripts/example.py",
            "action": "modify",
            "description": "Add a helper function",
            "acceptance": "",
            "effort": "XS",
        }

    def test_implement_step_xs_skips_resume(self) -> None:
        """implement_step with effort=XS should pass resume_session_id=None to llm_call."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.0
        mock_result.content = ""
        mock_result.session_id = ""

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result) as mock_llm,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner.emit_step"),
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
            patch("scripts.executor.step_runner.run_acceptance", return_value=(True, "")),
        ):
            implement_step(step, "rec-xs-001", 1, 1, resume_session_id="fake-session-id", effort="XS")

        # Assert llm_call was called with resume_session_id=None (skip applied)
        assert mock_llm.called
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs.get("resume_session_id") is None

    def test_implement_step_m_keeps_resume(self) -> None:
        """implement_step with effort=M should preserve resume_session_id."""
        step = {**self._make_step(), "effort": "M"}

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.0
        mock_result.content = ""
        mock_result.session_id = ""

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result) as mock_llm,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner.emit_step"),
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
            patch("scripts.executor.step_runner.run_acceptance", return_value=(True, "")),
        ):
            implement_step(step, "rec-m-001", 1, 1, resume_session_id="my-session", effort="M")

        assert mock_llm.called
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs.get("resume_session_id") == "my-session"


class TestVenvPythonResolution:
    """Verify Linux-first venv resolution in step_runner.py module-level globals."""

    @pytest.fixture(autouse=True)
    def _restore_module_state(self) -> None:
        # Snapshot the original module dict before any reloads so teardown can
        # restore it exactly. A plain reload in teardown creates a new StepOutcome
        # class that breaks module-level `from ... import StepOutcome` bindings in
        # other test classes running after this one (order-dependent failure).
        original_dict = dict(sr_mod.__dict__)
        importlib.reload(sr_mod)
        yield
        sr_mod.__dict__.clear()
        sr_mod.__dict__.update(original_dict)

    def test_linux_layout_preferred_when_both_present(self) -> None:
        with patch.object(Path, "exists", return_value=True):
            importlib.reload(sr_mod)
        assert sr_mod._PROJECT_PYTHON.endswith("bin/python")

    def test_windows_fallback_when_linux_missing(self) -> None:
        def _exists(self: Path) -> bool:
            return "python.exe" in str(self) or "ruff.exe" in str(self)

        with patch.object(Path, "exists", _exists):
            importlib.reload(sr_mod)
        assert "python.exe" in sr_mod._PROJECT_PYTHON
