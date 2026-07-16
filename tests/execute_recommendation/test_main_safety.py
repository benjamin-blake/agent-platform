"""Main-branch safety tests: jsonl-clean, acceptance-on-main, checkout-main-safely (rec-2709 Wave 2)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    _check_acceptance_on_main,
    _check_jsonl_clean,
    _checkout_main_safely,
)


class TestCheckJsonlClean:
    """Regression tests for _check_jsonl_clean() preflight guard.

    The guard uses ``git diff HEAD --quiet -- logs/.recommendations-log.jsonl``
    (pathspec-scoped) so staged and unstaged edits to this one tracked file
    trigger an abort. Tests cover both the standalone (ensure_feature_branch)
    and compound (_ensure_compound_branch) execution surfaces.
    """

    # ------------------------------------------------------------------
    # Unit tests for the helper itself
    # ------------------------------------------------------------------

    def test_clean_returns_true(self):
        """git diff HEAD --quiet exits 0 (clean) => helper returns True."""
        clean = MagicMock(returncode=0, stdout="", stderr="")
        with patch("scripts.execute_recommendation.subprocess.run", return_value=clean) as mock_run:
            result = _check_jsonl_clean()
        assert result is True
        called_cmd = mock_run.call_args[0][0]
        assert "diff" in called_cmd
        assert "HEAD" in called_cmd
        assert "--quiet" in called_cmd
        assert "logs/.recommendations-log.jsonl" in called_cmd

    def test_dirty_returns_false(self):
        """git diff HEAD --quiet exits 1 (dirty) => helper returns False."""
        dirty = MagicMock(returncode=1, stdout="", stderr="")
        with patch("scripts.execute_recommendation.subprocess.run", return_value=dirty):
            result = _check_jsonl_clean()
        assert result is False

    def test_timeout_returns_false(self):
        """Timeout during git diff => helper returns False without raising."""
        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git diff", timeout=10),
        ):
            result = _check_jsonl_clean()
        assert result is False

    def test_unexpected_exception_returns_false(self):
        """Unexpected exception => helper returns False without raising."""
        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            result = _check_jsonl_clean()
        assert result is False

    # ------------------------------------------------------------------
    # Standalone execution surface: ensure_feature_branch
    # ------------------------------------------------------------------

    def test_standalone_aborts_when_jsonl_dirty(self):
        """ensure_feature_branch returns False and skips branch creation when JSONL is dirty."""
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")
        dirty = MagicMock(returncode=1, stdout="", stderr="")

        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=[branch_result, dirty],
        ) as mock_run:
            from scripts.execute_recommendation import ensure_feature_branch

            result = ensure_feature_branch("rec-394")

        assert result is False
        # Only 2 calls: branch --show-current + git diff; no fetch or checkout
        assert mock_run.call_count == 2

    def test_standalone_proceeds_when_jsonl_clean(self):
        """ensure_feature_branch continues to branch creation when JSONL is clean."""
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")
        clean = MagicMock(returncode=0, stdout="", stderr="")
        fetch_ok = MagicMock(returncode=0, stdout="", stderr="")
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=[branch_result, clean, fetch_ok, checkout_ok],
        ):
            from scripts.execute_recommendation import ensure_feature_branch

            result = ensure_feature_branch("rec-394")

        assert result is True

    # ------------------------------------------------------------------
    # Compound execution surface: execute_compound
    # ------------------------------------------------------------------

    def test_compound_aborts_when_jsonl_dirty(self):
        """execute_compound returns early with all-failed summary when JSONL is dirty."""
        from scripts.execute_recommendation import execute_compound

        # _ensure_compound_branch internally checks _check_jsonl_clean (deferred import).
        # Simulate: on main branch, then dirty JSONL -> branch creation fails -> all fail.
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")

        with (
            patch(
                "scripts.executor.batch.subprocess.run",
                return_value=branch_result,
            ),
            patch(
                "scripts.execute_recommendation._check_jsonl_clean",
                return_value=False,
            ),
        ):
            result = execute_compound(["rec-394", "rec-395"])

        assert result["succeeded"] == 0
        assert result["failed"] == 2

    def test_compound_proceeds_when_jsonl_clean(self):
        """execute_compound calls _ensure_compound_branch and proceeds when JSONL is clean."""
        from scripts.execute_recommendation import execute_compound

        with patch(
            "scripts.executor.batch._ensure_compound_branch",
            return_value=True,
        ) as mock_branch:
            with patch("scripts.executor.jsonl_store.load_recommendation", return_value=None):
                result = execute_compound(["rec-394"])

        mock_branch.assert_called_once_with("agent/compound-rec-394")
        # rec not found => failed, but compound branch creation was attempted
        assert result["attempted"] == 1
        assert result["failed"] == 1


class TestCheckAcceptanceOnMain:
    """Test _check_acceptance_on_main function."""

    def test_acceptance_passes_on_main(self):
        """Test acceptance passes on main -> return True."""
        mock_subprocess_calls = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            mock_subprocess_calls.append(cmd)
            result = MagicMock()
            if "git" in cmd and "log" in cmd:
                result.stdout = "abc123 Test commit\n"
            else:
                result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                        assert result is True, "Expected True when acceptance passes on main"
                        mock_update.assert_called_once()
                        call_args = mock_update.call_args[0]
                        assert call_args[0] == "rec-test"
                        assert call_args[1]["status"] == "closed"
                        assert call_args[1]["execution_result"] == "already_implemented"

        # 1 (branch) + 3 (checkout_main no-restore) + 1 (git log) + 4 (finally restore) = 9
        expected = 9
        assert len(mock_subprocess_calls) == expected, (
            f"Expected {expected} subprocess calls, got {len(mock_subprocess_calls)}"
        )

    def test_acceptance_fails_on_main(self):
        """Test acceptance fails on main -> return False."""
        mock_subprocess_calls = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            mock_subprocess_calls.append(cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=False):
                with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                    result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                    assert result is False, "Expected False when acceptance fails on main"
                    mock_update.assert_not_called()

        # 1 (branch) + 3 (checkout_main no-restore) + 4 (finally restore) = 8, no git log call
        expected = 8
        assert len(mock_subprocess_calls) == expected, (
            f"Expected {expected} subprocess calls, got {len(mock_subprocess_calls)}"
        )

    def test_empty_acceptance_command(self):
        """Test empty acceptance command -> return False."""
        with patch("scripts.executor.acceptance_lint.subprocess.run") as mock_run:
            result = _check_acceptance_on_main("rec-test", "", "agent/rec-test")
            assert result is False, "Expected False for empty acceptance command"
            mock_run.assert_not_called()

    def test_whitespace_only_acceptance(self):
        """Test whitespace-only acceptance command -> return False."""
        with patch("scripts.executor.acceptance_lint.subprocess.run") as mock_run:
            result = _check_acceptance_on_main("rec-test", "   \n   ", "agent/rec-test")
            assert result is False, "Expected False for whitespace-only acceptance"
            mock_run.assert_not_called()

    def test_git_checkout_main_fails(self):
        """Test git checkout main fails -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if cmd and "checkout" in cmd and "main" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
            assert result is False, "Expected False when git checkout to main fails"

    def test_git_checkout_branch_fails(self):
        """Test git checkout back to branch fails inside _checkout_main_safely -> return False."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 4:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.update_recommendation_status"):
                    result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                    assert result is False, "Expected False when checkout back to branch fails"

    def test_acceptance_check_timeout(self):
        """Test subprocess timeout during acceptance check -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if cmd and "branch" in cmd and "--show-current" in cmd:
                return MagicMock(stdout="agent/rec-test", returncode=0)
            raise subprocess.TimeoutExpired("git", 5)

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
            assert result is False, "Expected False on subprocess timeout"

    def test_branch_switching_sequence(self):
        """Verify correct branch switching sequence within _checkout_main_safely."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status"):
                        _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")

        assert len(call_sequence) >= 5, f"Expected at least 5 subprocess calls, got {len(call_sequence)}"
        assert any("branch --show-current" in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git branch --show-current' in call sequence"
        )
        assert any("stash" in " ".join(cmd) and "pop" not in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git stash' (without pop) in call sequence"
        )
        assert any("checkout main" in " ".join(cmd) for cmd in call_sequence), "Expected 'git checkout main' in call sequence"
        assert any("checkout agent/rec-test" in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git checkout agent/rec-test' in call sequence"
        )
        assert any("stash pop" in " ".join(cmd) for cmd in call_sequence), "Expected 'git stash pop' in call sequence"

    def test_acceptance_ambiguous_zero_commits(self):
        """Test acceptance passes on main but zero commits since rec date -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            _cmd = args[0] if args else []
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                        assert result is False, "Expected False when no commits found since rec date"
                        mock_update.assert_not_called()

    def test_acceptance_ambiguous_with_env_override(self):
        """Test zero commits but ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED=true -> return True."""

        def mock_subprocess_run(*args, **kwargs):
            _cmd = args[0] if args else []
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        env_override = {"ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED": "true"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        with patch.dict("os.environ", env_override):
                            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                            assert result is True, "Expected True when ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED=true"
                            mock_update.assert_called_once()
                            call_args = mock_update.call_args[0]
                            assert call_args[1]["execution_result"] == "already_implemented"


class TestCheckoutMainSafely:
    """Test _checkout_main_safely function."""

    def test_no_restore_branch(self):
        """Test checkout to main without restore_branch - stash pop happens on main."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

        assert len(call_sequence) == 3, f"Expected 3 calls, got {len(call_sequence)}"
        assert call_sequence[0] == ["git", "stash"], "Expected git stash"
        assert call_sequence[1] == ["git", "checkout", "main"], "Expected git checkout main"
        assert call_sequence[2] == ["git", "stash", "pop"], "Expected git stash pop"

    def test_with_restore_branch(self):
        """Test with restore_branch - stash pop happens after branch restoration."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely("agent/rec-test")

        assert len(call_sequence) == 4, f"Expected 4 calls, got {len(call_sequence)}"
        assert call_sequence[0] == ["git", "stash"], "Expected git stash"
        assert call_sequence[1] == ["git", "checkout", "main"], "Expected git checkout main"
        assert call_sequence[2] == ["git", "checkout", "agent/rec-test"], "Expected checkout to restore_branch"
        assert call_sequence[3] == ["git", "stash", "pop"], "Expected git stash pop after restore"

    def test_stash_fails(self):
        """Test git stash failure raises CalledProcessError."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if "stash" in cmd and len(cmd) == 2:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely()

    def test_checkout_main_fails(self):
        """Test git checkout main failure raises CalledProcessError."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 2:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely()

    def test_checkout_restore_branch_fails(self):
        """Test checkout to restore_branch failure raises CalledProcessError."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 3:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely("agent/rec-test")

    def test_stash_pop_does_not_raise(self):
        """Test stash pop failure does not raise (check=False not set, but capture_output is)."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            result = MagicMock()
            result.returncode = 1 if call_count[0] == 3 else 0
            if result.returncode != 0 and kwargs.get("check"):
                raise subprocess.CalledProcessError(result.returncode, cmd)
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

    def test_timeout_during_stash(self):
        """Test timeout during git stash raises TimeoutExpired."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if "stash" in cmd and len(cmd) == 2:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.TimeoutExpired):
                _checkout_main_safely()

    def test_timeout_during_checkout_main(self):
        """Test timeout during git checkout main raises TimeoutExpired."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 2:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.TimeoutExpired):
                _checkout_main_safely()

    def test_encoding_and_error_handling(self):
        """Verify text=True, encoding=utf-8, errors=replace are used."""
        call_kwargs_list = []

        def mock_subprocess_run(*args, **kwargs):
            call_kwargs_list.append(kwargs)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

        for kwargs in call_kwargs_list:
            assert kwargs.get("text") is True, "Expected text=True"
            assert kwargs.get("encoding") == "utf-8", "Expected encoding=utf-8"
            assert kwargs.get("errors") == "replace", "Expected errors=replace"
