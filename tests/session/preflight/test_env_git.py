"""env_git-surface tests: check_venv, get_git_status, check_main_freshness, worktree detection,
run_log_sync, activate-hint printing, recent-main-commits parsing (rec-2709 Wave 4).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestCheckVenv:
    def test_correct_venv_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "session_preflight.sys.executable",
            "C:/Users/user/Git Repos/agent-platform/.venv/Scripts/python.exe",
        )
        monkeypatch.setattr("scripts.preflight._common.ROOT", Path("C:/Users/user/Git Repos/agent-platform"))
        assert _preflight.check_venv() is True

    def test_wrong_venv_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "session_preflight.sys.executable",
            "C:/Users/user/Git Repos/da-data-athena/.venv/Scripts/python.exe",
        )
        monkeypatch.setattr("scripts.preflight._common.ROOT", Path("C:/Users/user/Git Repos/agent-platform"))
        assert _preflight.check_venv() is False


class TestGetGitStatus:
    def test_clean_branch(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "main\n"
            elif "--porcelain" in cmd:
                result.stdout = ""
            elif "list" in cmd:
                result.stdout = ""
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            branch, uncommitted, stash = _preflight.get_git_status()

        assert branch == "main"
        assert uncommitted is False
        assert stash == []

    def test_uncommitted_changes_detected(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "agent/test-branch\n"
            elif "--porcelain" in cmd:
                result.stdout = " M scripts/some_file.py\n"
            elif "list" in cmd:
                result.stdout = ""
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            branch, uncommitted, stash = _preflight.get_git_status()

        assert branch == "agent/test-branch"
        assert uncommitted is True

    def test_stash_entries_parsed(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "main\n"
            elif "--porcelain" in cmd:
                result.stdout = ""
            elif "list" in cmd:
                result.stdout = "stash@{0}: WIP on main: abc123 some work\nstash@{1}: WIP on main: def456 other\n"
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            _, _, stash = _preflight.get_git_status()

        assert len(stash) == 2
        assert "stash@{0}" in stash[0]


class TestCheckMainFreshness:
    def test_fetch_failure_returns_fetch_failed_status(self) -> None:
        fetch_fail = MagicMock(returncode=1, stderr="network unreachable", stdout="")
        with patch("session_preflight.subprocess.run", return_value=fetch_fail):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"
        assert result["commits_behind"] is None
        assert result["commits_ahead"] is None
        assert result["main_files_changed_since_branch"] == []
        assert "network unreachable" in result["error"]

    def test_fetch_filenotfound_returns_fetch_failed_status(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=FileNotFoundError("git missing")):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"
        assert "git missing" in result["error"]

    def test_fetch_timeout_returns_fetch_failed_status(self) -> None:
        with patch(
            "session_preflight.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"

    def test_on_main_branch_returns_zero_zero(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="0\t0\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 0
        assert result["commits_ahead"] == 0
        assert result["main_files_changed_since_branch"] == []

    def test_branch_ahead_of_main_returns_zero_behind(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="0\t3\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 0
        assert result["commits_ahead"] == 3
        assert result["main_files_changed_since_branch"] == []

    def test_branch_behind_main_lists_changed_files(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="5\t2\n")
        merge_base = MagicMock(returncode=0, stdout="abc123\n")
        diff = MagicMock(returncode=0, stdout="docs/DECISIONS.md\nscripts/foo.py\n\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            if cmd[:2] == ["git", "merge-base"]:
                return merge_base
            if cmd[:2] == ["git", "diff"]:
                return diff
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 5
        assert result["commits_ahead"] == 2
        assert result["main_files_changed_since_branch"] == ["docs/DECISIONS.md", "scripts/foo.py"]

    def test_rev_list_failure_returns_diff_failed_status(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=128, stdout="")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "diff_failed"
        assert result["commits_behind"] is None


class TestCheckVenvWorktree:
    """Tests for check_venv() with worktree scenario and is_worktree()."""

    def test_check_venv_accepts_root_venv_windows(self, tmp_path: Path) -> None:
        """check_venv() returns True when sys.executable is inside ROOT/.venv (Windows layout)."""
        fake_root = tmp_path / "agent-platform"
        venv_exe = fake_root / ".venv" / "Scripts" / "python.exe"
        venv_exe.parent.mkdir(parents=True)
        venv_exe.touch()
        with (
            patch("scripts.preflight._common.ROOT", fake_root),
            patch("session_preflight.sys.executable", str(venv_exe)),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_accepts_root_venv_linux(self, tmp_path: Path) -> None:
        """check_venv() returns True when sys.executable is inside ROOT/.venv (Linux layout)."""
        fake_root = tmp_path / "agent-platform"
        venv_exe = fake_root / ".venv" / "bin" / "python"
        venv_exe.parent.mkdir(parents=True)
        venv_exe.touch()
        with (
            patch("scripts.preflight._common.ROOT", fake_root),
            patch("session_preflight.sys.executable", str(venv_exe)),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_accepts_root_with_pyvenv_cfg(self, tmp_path: Path) -> None:
        """check_venv() returns True via the name-independent fallback when ROOT has its own .venv.

        The on-disk directory name may stay 'agent-platform' (or anything) after a GitHub rename,
        so the fallback checks for ROOT/.venv/pyvenv.cfg rather than matching the repo name.
        """
        fake_root = tmp_path / "some-renamed-dir"
        (fake_root / ".venv").mkdir(parents=True)
        (fake_root / ".venv" / "pyvenv.cfg").touch()
        with (
            patch("scripts.preflight._common.ROOT", fake_root),
            patch("sys.executable", "C:/unrelated/path/python.exe"),
            patch("session_preflight.sys.executable", "C:/unrelated/path/python.exe"),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_rejects_wrong_venv(self, tmp_path: Path) -> None:
        """check_venv() returns False when exe is a different repo's venv and ROOT has no .venv."""
        fake_root = tmp_path / "agent-platform"
        fake_root.mkdir()  # deliberately no .venv -> fallback must be False
        with (
            patch("scripts.preflight._common.ROOT", fake_root),
            patch("sys.executable", "C:/other-repo/.venv/Scripts/python.exe"),
            patch("session_preflight.sys.executable", "C:/other-repo/.venv/Scripts/python.exe"),
        ):
            assert _preflight.check_venv() is False

    def test_is_worktree_returns_true_when_cwd_differs_from_toplevel(self) -> None:
        """is_worktree() returns True when git toplevel differs from CWD."""
        mock_result = MagicMock(returncode=0, stdout="/main/repo\n")
        with (
            patch("session_preflight.subprocess.run", return_value=mock_result),
            patch("session_preflight.Path.cwd", return_value=Path("/main/repo/worktree")),
        ):
            assert _preflight.is_worktree() is True

    def test_is_worktree_returns_false_when_cwd_equals_toplevel(self) -> None:
        """is_worktree() returns False when CWD matches git toplevel."""
        mock_result = MagicMock(returncode=0, stdout="/main/repo\n")
        with (
            patch("session_preflight.subprocess.run", return_value=mock_result),
            patch("session_preflight.Path.cwd", return_value=Path("/main/repo")),
        ):
            assert _preflight.is_worktree() is False

    def test_is_worktree_returns_false_on_git_failure(self) -> None:
        """is_worktree() returns False when git rev-parse fails."""
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("session_preflight.subprocess.run", return_value=mock_result):
            assert _preflight.is_worktree() is False


class TestLogSync:
    """Tests for run_log_sync() in session_preflight."""

    def _make_run(
        self,
        branch: str = "main",
        porcelain: str = "",
        add_rc: int = 0,
        commit_rc: int = 0,
        push_rc: int = 0,
        push_stderr: str = "",
    ) -> object:
        """Helper to build a mock subprocess.run side_effect for run_log_sync."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            if "--show-current" in cmd:
                result.stdout = branch + "\n"
            elif "--porcelain" in cmd:
                result.stdout = porcelain
            elif "add" in cmd:
                result.returncode = add_rc
                result.stderr = "add error" if add_rc != 0 else ""
            elif "commit" in cmd:
                result.returncode = commit_rc
                result.stderr = "commit error" if commit_rc != 0 else ""
            elif "push" in cmd:
                result.returncode = push_rc
                result.stderr = push_stderr
            return result

        return mock_run

    def test_log_sync_skipped_on_feature_branch(self) -> None:
        mock_run = self._make_run(branch="agent/foo")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "skipped"

    def test_log_sync_committed_when_only_logs_dirty(self) -> None:
        porcelain = " M logs/.friction-analysis-log.jsonl\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain)
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "committed"
        assert "logs/.friction-analysis-log.jsonl" in result["files"]

    def test_log_sync_skipped_when_non_log_dirty(self) -> None:
        porcelain = " M src/main.py\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain)
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "skipped"

    def test_log_sync_conflict_on_push_fail(self) -> None:
        porcelain = " M logs/.retro-lite-log.jsonl\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain, push_rc=1, push_stderr="push failed")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "conflict"
        assert "error" in result

    def test_log_sync_clean_when_no_dirty_files(self) -> None:
        mock_run = self._make_run(branch="main", porcelain="")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "clean"


class TestActivateHint:
    """Verify _print_activate_hint() emits the correct activate line per platform."""

    def test_activate_hint_linux(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        _preflight._print_activate_hint()
        out = capsys.readouterr().out
        assert ".venv/bin/activate" in out
        assert ".venv/Scripts/activate" not in out

    def test_activate_hint_windows(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        _preflight._print_activate_hint()
        out = capsys.readouterr().out
        assert ".venv/Scripts/activate" in out
        assert ".venv/bin/activate" not in out


class TestGetRecentMainCommits:
    """Tests for _get_recent_main_commits()."""

    _GIT_LOG_OUTPUT = (
        "COMMIT:abc12345|2026-06-12T10:00:00+00:00|feat(scope): fix bar\n"
        "scripts/foo.py\n"
        "scripts/bar.py\n"
        "\n"
        "COMMIT:def67890|2026-06-11T09:00:00+00:00|fix: repair baz\n"
        "scripts/baz.py\n"
    )

    def _make_git_result(self, stdout: str, returncode: int = 0) -> MagicMock:
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        return r

    def test_returns_list_of_commits(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result(self._GIT_LOG_OUTPUT)):
            result = _preflight._get_recent_main_commits()
        assert len(result) == 2
        assert result[0]["sha"] == "abc12345"
        assert result[0]["subject"] == "feat(scope): fix bar"
        assert "scripts/foo.py" in result[0]["files"]
        assert result[1]["sha"] == "def67890"

    def test_returns_empty_on_nonzero_exit(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result("", returncode=1)):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_returns_empty_on_oserror(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=OSError("git not found")):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_returns_empty_on_timeout(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_empty_output_returns_empty(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result("")):
            result = _preflight._get_recent_main_commits()
        assert result == []
