"""close / telemetry-session concern: tests/session/postflight/test_close.py (rec-2709 Wave 10).

Split from the former tests/test_session_postflight.py monolith: TestCloseMode,
TestCloseTelemetrySession.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_postflight_module import postflight as _postflight


class TestCloseMode:
    """Tests for session_postflight.run_close()."""

    def _mock_sanity_result(self, status: str = "PASS") -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = json.dumps({"status": status})
        r.stderr = ""
        return r

    def test_intent_verification_with_plan(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Intent text is extracted from the plan file and included in output."""
        plan = tmp_path / "PLAN-test.md"
        plan.write_text(
            "## Intent\nVerify the login feature works correctly.\n\n## Scope\n",
            encoding="utf-8",
        )
        diff_result = MagicMock(returncode=0, stdout="1 file changed, 10 insertions(+)", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            rc = _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["details"]["intent_text"] == "Verify the login feature works correctly."
        assert data["sanity_status"] == "PASS"

    def test_intent_achieved_true_when_files_changed(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """intent_achieved is True when git diff shows changes."""
        plan = tmp_path / "PLAN-test.md"
        plan.write_text("## Intent\nDo something.\n\n## Scope\n", encoding="utf-8")
        diff_result = MagicMock(returncode=0, stdout="2 files changed, 5 insertions(+)", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["intent_achieved"] is True

    def test_session_log_entry_template_generated(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """session_log_entry contains branch, plan name, and diff summary."""
        plan = tmp_path / "PLAN-my-feature.md"
        plan.write_text("## Intent\nShip the feature.\n\n## Scope\n", encoding="utf-8")
        diff_result = MagicMock(returncode=0, stdout="3 files changed", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
            patch("scripts.postflight._common._current_branch", return_value="agent/my-feature"),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        log = data["session_log_entry"]
        assert "agent/my-feature" in log
        assert "PLAN-my-feature.md" in log
        assert "3 files changed" in log

    def test_no_plan_file_intent_is_none(self, capsys: pytest.CaptureFixture) -> None:
        """When no plan file exists, intent_achieved is None."""
        diff_result = MagicMock(returncode=0, stdout="", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["intent_achieved"] is None


class TestCloseTelemetrySession:
    """Tests for close_telemetry_session()."""

    def test_state_file_exists_calls_close_session(self, tmp_path: Path) -> None:
        """When state file exists, restores ctx and calls close_session."""
        import json as _json

        state_file = tmp_path / ".telemetry-active-session.json"
        state = {
            "session_id": "test-uuid-1234",
            "workflow": "implement",
            "branch": "agent/test",
            "started_at": "2025-01-01T00:00:00+00:00",
        }
        state_file.write_text(_json.dumps(state), encoding="utf-8")

        mock_tel = MagicMock()
        mock_ctx = MagicMock()
        mock_tel.get_context.return_value = mock_ctx

        original = sys.modules.get("scripts.executor.telemetry")
        sys.modules["scripts.executor.telemetry"] = mock_tel
        try:
            with patch("scripts.postflight._common.TELEMETRY_ACTIVE_SESSION_FILE", state_file):
                _postflight.close_telemetry_session(outcome="success", files_changed=3)
        finally:
            if original is not None:
                sys.modules["scripts.executor.telemetry"] = original
            else:
                sys.modules.pop("scripts.executor.telemetry", None)

        mock_tel.close_session.assert_called_once()
        call_kwargs = mock_tel.close_session.call_args.kwargs
        assert call_kwargs.get("outcome") == "success"
        assert call_kwargs.get("files_changed") == 3
        assert not state_file.exists()

    def test_missing_state_file_does_not_crash(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """When state file is absent, logs a warning and returns without error."""
        missing = tmp_path / ".telemetry-active-session.json"
        with patch("scripts.postflight._common.TELEMETRY_ACTIVE_SESSION_FILE", missing):
            _postflight.close_telemetry_session(outcome="success")

        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "Skipping" in captured.err
