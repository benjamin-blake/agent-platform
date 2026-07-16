"""push / PR / CI-poll concern: tests/session/postflight/test_push.py (rec-2709 Wave 10).

Split from the former tests/test_session_postflight.py monolith: TestPushUpstreamDetection,
TestCIPollingTimeout. Uses patch("session_postflight.time.sleep/.time") (the synthetic name
resolves via the shared singleton in tests/fixtures/session_postflight_module.py).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_postflight_module import postflight as _postflight


class TestPushUpstreamDetection:
    def test_uses_set_upstream_on_push(self) -> None:
        called_cmds: list[list] = []

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            called_cmds.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", side_effect=[0, 1000]),  # instant timeout
        ):
            _postflight.run_push()

        push_cmd = next((c for c in called_cmds if "push" in c and "--set-upstream" in c), None)
        assert push_cmd is not None


class TestCIPollingTimeout:
    def test_returns_ci_timeout_json(self, capsys: pytest.CaptureFixture) -> None:
        def mock_time() -> float:
            # First call returns 0, subsequent calls return > timeout
            if not hasattr(mock_time, "_called"):
                mock_time._called = 0  # type: ignore[attr-defined]
            mock_time._called += 1  # type: ignore[attr-defined]
            return 0 if mock_time._called <= 1 else 9999  # type: ignore[attr-defined]

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", side_effect=mock_time),
        ):
            _postflight.run_push()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "ci_timeout"

    def test_clears_checkpoint_on_successful_merge(self, capsys: pytest.CaptureFixture) -> None:
        # gh pr view --json statusCheckRollup: status=COMPLETED, conclusion=SUCCESS means passed
        sr_data = json.dumps(
            {
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "CI", "name": "validate-python"}
                ]
            }
        )
        run_list = json.dumps([{"databaseId": 99}])
        pr_view = json.dumps({"url": "https://github.com/pr/1", "number": 1})

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if "pr" in cmd and "view" in cmd and "statusCheckRollup" in cmd:
                result.stdout = sr_data
            elif "run" in cmd and "list" in cmd:
                result.stdout = run_list
            elif "pr" in cmd and "view" in cmd:
                result.stdout = pr_view
            else:
                result.stdout = ""
            return result

        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("scripts.postflight._common.clear_checkpoint") as mock_clear,
        ):
            rc = _postflight.run_push()

        assert rc == 0
        mock_clear.assert_called_once()

    def test_does_not_merge_when_a_check_fails(self, capsys: pytest.CaptureFixture) -> None:
        """Reproduces the original bug: pre-commit passes but CI fails — no merge."""
        # Two checks: pre-commit passed (SUCCESS), CI failed (FAILURE)
        sr_data = json.dumps(
            {
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "Pre-commit check", "name": "pre-commit"},
                    {"status": "COMPLETED", "conclusion": "FAILURE", "workflowName": "CI", "name": "validate-python"},
                ]
            }
        )
        pr_view = json.dumps({"url": "https://github.com/pr/1", "number": 1})

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if "pr" in cmd and "view" in cmd and "statusCheckRollup" in cmd:
                result.stdout = sr_data
            elif "run" in cmd and "list" in cmd:
                result.stdout = json.dumps([{"databaseId": 42}])
            elif "pr" in cmd and "view" in cmd:
                result.stdout = pr_view
            else:
                result.stdout = ""
            return result

        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("scripts.postflight._common.clear_checkpoint") as mock_clear,
        ):
            rc = _postflight.run_push()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 1
        assert data["status"] == "ci_failed"
        assert "CI" in data["error_summary"]
        mock_clear.assert_called_once()  # checkpoint cleared on failure too

    def test_keeps_polling_while_checks_pending(self, capsys: pytest.CaptureFixture) -> None:
        """Keeps polling when some checks are still pending, stops when all pass."""
        pr_view = json.dumps({"url": "https://github.com/pr/1", "number": 1})
        # First call: one check in progress; second call: all completed
        pending_sr = json.dumps(
            {
                "statusCheckRollup": [
                    {"status": "IN_PROGRESS", "conclusion": None, "workflowName": "CI", "name": "validate-python"}
                ]
            }
        )
        passed_sr = json.dumps(
            {
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "CI", "name": "validate-python"}
                ]
            }
        )
        call_counts: dict[str, int] = {"sr": 0}

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if "pr" in cmd and "view" in cmd and "statusCheckRollup" in cmd:
                call_counts["sr"] += 1
                result.stdout = pending_sr if call_counts["sr"] == 1 else passed_sr
            elif "run" in cmd and "list" in cmd:
                result.stdout = json.dumps([{"databaseId": 77}])
            elif "pr" in cmd and "view" in cmd:
                result.stdout = pr_view
            else:
                result.stdout = ""
            return result

        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("scripts.postflight._common.clear_checkpoint"),
        ):
            rc = _postflight.run_push()

        assert rc == 0
        assert call_counts["sr"] == 2  # polled twice before merging
