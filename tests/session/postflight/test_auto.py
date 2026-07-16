"""run_auto full-sequence concern: tests/session/postflight/test_auto.py (rec-2709 Wave 10).

Split from the former tests/test_session_postflight.py monolith: TestAutoMode,
TestRetiredDrainBlocks, TestRunAutoCompactAll. Imports MODULE_PATH from the shared loader for the
source-text assertion.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_postflight_module import MODULE_PATH as _MODULE_PATH
from tests.fixtures.session_postflight_module import postflight as _postflight


class TestAutoMode:
    """Tests for run_auto(): the full session-close sequence in one call."""

    def _close_output(self, sanity_status: str = "PASS") -> str:
        return json.dumps(
            {
                "intent_achieved": True,
                "session_log_entry": "## [2026-04-07] session",
                "sanity_status": sanity_status,
                "details": {},
            }
        )

    def _push_output(self, status: str = "merged") -> str:
        return json.dumps({"status": status, "pr_url": "https://github.com/pr/1"})

    def test_happy_path_returns_merged(self, capsys: pytest.CaptureFixture) -> None:
        """All steps succeed -> rc=0 and status merged in output."""
        close_out = self._close_output("PASS")
        push_out = self._push_output("merged")

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", return_value={"pulled": {}}),
            patch("scripts.postflight.housekeeping._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test", 5, 1)

        assert rc == 0
        captured = capsys.readouterr()
        assert '"merged"' in captured.out

    def test_validate_failure_stops_early(self, capsys: pytest.CaptureFixture) -> None:
        """If --validate fails, auto stops and returns validate_failed."""
        with (
            patch("session_postflight.run_validate", return_value=1),
            patch("session_postflight.run_close") as mock_close,
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 1
        mock_close.assert_not_called()
        captured = capsys.readouterr()
        assert '"validate_failed"' in captured.out

    def test_sanity_fail_stops_before_commit(self, capsys: pytest.CaptureFixture) -> None:
        """If close returns sanity_status FAIL, auto should stop and not commit."""
        close_out = self._close_output("FAIL")

        def fake_close() -> int:
            print(close_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("session_postflight.run_commit") as mock_commit,
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 1
        mock_commit.assert_not_called()
        captured = capsys.readouterr()
        assert '"sanity_failed"' in captured.out

    def test_ci_failed_propagated(self, capsys: pytest.CaptureFixture) -> None:
        """If push returns ci_failed, run_auto propagates that status."""
        close_out = self._close_output("PASS")
        push_out = self._push_output("ci_failed")

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 1  # ci_failed exits non-zero in production

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", return_value={"pulled": {}}),
            patch("scripts.postflight.housekeeping._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc != 0
        captured = capsys.readouterr()
        assert '"ci_failed"' in captured.out

    def test_auto_log_housekeeping_failure_ignored(self, capsys: pytest.CaptureFixture) -> None:
        """Log-housekeeping failure does not affect overall return code."""
        close_out = self._close_output("PASS")
        push_out = self._push_output("merged")

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=1),  # failure
            patch("scripts.ops_data_portal.sync", return_value={"pulled": {}}),
            patch("scripts.postflight.housekeeping._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0  # best-effort: log-housekeeping failure must not affect rc
        captured = capsys.readouterr()
        assert '"merged"' in captured.out

    def test_auto_rejects_empty_commit_message(self, capsys: pytest.CaptureFixture) -> None:
        """run_auto returns rc=1 with clear error when commit message is empty."""
        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", return_value=0),
        ):
            rc = _postflight.run_auto("")

        assert rc == 1
        captured = capsys.readouterr()
        assert '"commit_failed"' in captured.out

    def test_auto_refreshes_read_cache_via_portal_sync(self, capsys: pytest.CaptureFixture) -> None:
        """Step 8: the portal sync (cache pull) runs during run_auto; merged status appears in output."""
        close_out = self._close_output("PASS")
        push_out = self._push_output("merged")

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", return_value={"pulled": {"ops_recommendations": 3}}) as mock_sync,
            patch("scripts.postflight.housekeeping._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0
        mock_sync.assert_called_once()
        captured = capsys.readouterr()
        assert '"merged"' in captured.out


class TestRetiredDrainBlocks:
    """Decision 84 I-4: the pending-outbox drain blocks are gone from run_auto().

    The static-key invariant survives the retirement: run_auto() must still never
    spawn an 'aws sso login' subprocess.
    """

    def _close_output(self, sanity_status: str = "PASS") -> str:
        return json.dumps(
            {
                "intent_achieved": True,
                "session_log_entry": "## [2026-05-30] session",
                "sanity_status": sanity_status,
                "details": {},
            }
        )

    def _push_output(self, status: str = "merged") -> str:
        return json.dumps({"status": status, "pr_url": "https://github.com/pr/1"})

    def test_no_sso_login_subprocess_spawned(self, capsys: pytest.CaptureFixture) -> None:
        """run_auto() must never call subprocess.run(['aws', 'sso', 'login', ...])."""
        close_out = self._close_output()
        push_out = self._push_output()

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", return_value={"pulled": {}}),
            patch("scripts.postflight.housekeeping._stage_document_derived_tables"),
            patch("subprocess.run") as mock_subprocess,
        ):
            _postflight.run_auto("feat: test")

        # Confirm no 'aws sso login' call was made
        for call_args in mock_subprocess.call_args_list:
            cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("args", [])
            assert not ("sso" in cmd and "login" in cmd), f"Unexpected aws sso login call: {cmd}"

    def test_run_auto_source_has_no_drain_blocks(self) -> None:
        """The drain_pending / drain_pending_decisions blocks are deleted; step 7b is a retirement comment."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "drain_pending" not in source, "postflight must not reference the retired outbox drain"
        assert "retired" in source and "7b" in source  # the step-7b retirement comment documents the removal


# ---------------------------------------------------------------------------
# compact_all() integration in run_auto (Decision 50)
# ---------------------------------------------------------------------------


class TestRunAutoCompactAll:
    """Tests for ops_data_portal.sync() integration in run_auto (Decision 50 / Decision 84 step 8)."""

    def test_compact_all_called_in_run_auto(self, capsys: pytest.CaptureFixture) -> None:
        """ops_data_portal.sync() is called as step 8 of run_auto."""
        mock_sync = MagicMock(return_value=None)

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", return_value=0),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", return_value=0),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", mock_sync),
        ):
            _postflight.run_auto("feat: test")

        mock_sync.assert_called_once()

    def test_compact_all_exception_does_not_fail_run_auto(self, capsys: pytest.CaptureFixture) -> None:
        """ops_data_portal.sync() exception is caught and does not cause run_auto to fail."""
        push_out = json.dumps({"status": "merged", "pr_url": "https://github.com/test/pr/1"})

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", return_value=0),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", side_effect=RuntimeError("sync failed!")),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0

    def test_ops_writer_import_failure_handled_gracefully(self, capsys: pytest.CaptureFixture) -> None:
        """ops_data_portal.sync() ImportError is caught and does not fail run_auto."""
        push_out = json.dumps({"status": "merged", "pr_url": "https://github.com/test/pr/1"})

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", return_value=0),
            patch("scripts.postflight.housekeeping.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("scripts.postflight.remote.run_push", side_effect=fake_push),
            patch("scripts.postflight.housekeeping.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.sync", side_effect=ImportError("ops_data_portal not found")),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0
