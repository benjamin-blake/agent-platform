#!/usr/bin/env python3
"""Unit tests for scripts/session_postflight.py."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session_postflight.py"
_spec = importlib.util.spec_from_file_location("session_postflight", _MODULE_PATH)
assert _spec and _spec.loader
_postflight = importlib.util.module_from_spec(_spec)
sys.modules["session_postflight"] = _postflight
_spec.loader.exec_module(_postflight)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _mock_sync_ops_postflight():
    """Prevent real AWS calls from sync_ops inside run_auto() tests."""
    with patch("scripts.sync_ops.sync", return_value={"drained": {}, "pulled": {}}):
        yield


def _make_run(mapping: dict) -> object:
    """Helper: create a mock subprocess.run that returns based on command."""

    def mock_run(cmd: list, **kwargs: object) -> MagicMock:
        cmd_str = " ".join(str(c) for c in cmd)
        for key, (rc, stdout, stderr) in mapping.items():
            if key in cmd_str:
                result = MagicMock()
                result.returncode = rc
                result.stdout = stdout
                result.stderr = stderr
                return result
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    return mock_run


class TestValidateMode:
    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "Validation passed"
        result.stderr = ""
        with patch("session_postflight._run", return_value=result):
            rc = _postflight.run_validate()
        assert rc == 0

    def test_returns_nonzero_on_failure(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 1
        result.stdout = "ERROR: something failed"
        result.stderr = ""
        with patch("session_postflight._run", return_value=result):
            rc = _postflight.run_validate()
        assert rc == 1


class TestPreCommitSanity:
    def test_main_branch_returns_fail(self, capsys: pytest.CaptureFixture) -> None:
        with patch("session_postflight._current_branch", return_value="main"):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "FAIL"
        assert rc == 1

    def test_scope_comparison_detects_unplanned(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        plan_file = tmp_path / "PLAN-test.md"
        scope_content = (
            "## Scope\n\n| File | Action | Purpose |\n"
            "|------|--------|------|\n"
            "| `scripts/foo.py` | Create | test |\n\n## Next\n"
        )
        plan_file.write_text(scope_content, encoding="utf-8")
        with (
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=plan_file),
            patch("session_postflight._get_changed_files", return_value=["scripts/foo.py", "scripts/unplanned.py"]),
            patch("session_postflight._run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        ):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "WARN"
        assert "scripts/unplanned.py" in data["unplanned"]
        assert rc == 0

    def test_clean_scope_returns_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        plan_file = tmp_path / "PLAN-test.md"
        scope_content = (
            "## Scope\n\n| File | Action | Purpose |\n"
            "|------|--------|------|\n"
            "| `scripts/foo.py` | Create | test |\n\n## Next\n"
        )
        plan_file.write_text(scope_content, encoding="utf-8")
        with (
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=plan_file),
            patch("session_postflight._get_changed_files", return_value=["scripts/foo.py"]),
            patch("session_postflight._run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        ):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "PASS"
        assert rc == 0


class TestCommitRetry:
    def test_succeeds_on_first_attempt(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "1 file changed"
        result.stderr = ""
        with patch("session_postflight._run", return_value=result):
            rc = _postflight.run_commit("feat: test commit")
        assert rc == 0

    def test_retries_on_pre_commit_failure_then_succeeds(self) -> None:
        call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            result.stderr = ""
            cmd_str = " ".join(str(c) for c in cmd)
            if "commit" in cmd_str:
                call_count += 1
                if call_count <= 2:
                    result.returncode = 1
                    result.stdout = "pre-commit hook failed"
                else:
                    result.returncode = 0
                    result.stdout = "1 file changed"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("session_postflight._run", side_effect=mock_run):
            rc = _postflight.run_commit("feat: retry test")
        assert rc == 0
        assert call_count == 3

    def test_fails_after_max_retries(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 1
            result.stdout = "pre-commit hook failed"
            result.stderr = ""
            return result

        with patch("session_postflight._run", side_effect=mock_run):
            rc = _postflight.run_commit("feat: always fail")
        assert rc == 1


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
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._run", side_effect=mock_run),
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
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._run", side_effect=mock_run),
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
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("session_postflight.clear_checkpoint") as mock_clear,
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
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("session_postflight.clear_checkpoint") as mock_clear,
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
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._run", side_effect=mock_run),
            patch("session_postflight.time.sleep", return_value=None),
            patch("session_postflight.time.time", return_value=0),
            patch("session_postflight.clear_checkpoint"),
        ):
            rc = _postflight.run_push()

        assert rc == 0
        assert call_counts["sr"] == 2  # polled twice before merging


class TestMetricsMode:
    def test_returns_combined_json(self, capsys: pytest.CaptureFixture) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "metrics output"
        mock_result.stderr = ""
        with (
            patch("session_postflight._run", return_value=mock_result),
            patch("session_postflight.prune_telemetry_logs", return_value={"pruned": [], "skipped": []}),
        ):
            rc = _postflight.run_metrics()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "metrics" in data
        assert "plan_audit" in data
        assert rc == 0


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
            patch("session_postflight.find_plan_file", return_value=plan),
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight._run", side_effect=[diff_result, sanity_result]),
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
            patch("session_postflight.find_plan_file", return_value=plan),
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight._run", side_effect=[diff_result, sanity_result]),
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
            patch("session_postflight.find_plan_file", return_value=plan),
            patch("session_postflight._run", side_effect=[diff_result, sanity_result]),
            patch("session_postflight._current_branch", return_value="agent/my-feature"),
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
            patch("session_postflight.find_plan_file", return_value=None),
            patch("session_postflight._current_branch", return_value="agent/test"),
            patch("session_postflight._run", side_effect=[diff_result, sanity_result]),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["intent_achieved"] is None


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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("session_postflight._stage_document_derived_tables"),
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("session_postflight._stage_document_derived_tables"),
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=1),  # failure
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("session_postflight._stage_document_derived_tables"),
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

    def test_auto_recommendation_sync_in_output(self, capsys: pytest.CaptureFixture) -> None:
        """drain_pending is called during run_auto; merged status appears in JSON output."""
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 3, "skipped": 0}) as mock_drain,
            patch("session_postflight._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0
        mock_drain.assert_called_once()
        captured = capsys.readouterr()
        assert '"merged"' in captured.out


class TestCheckSsoGating:
    """Tests for the static-key SSO-gating logic in run_auto().

    Under the static-key assume-role model, run_auto() must:
    - Never spawn an 'aws sso login' subprocess.
    - Skip the drain (skip-and-continue) when _check_sso returns False.
    - Proceed with the drain when _check_sso returns True.
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("scripts.ops_data_portal.drain_pending_decisions", return_value={"drained": 0}),
            patch("session_postflight._stage_document_derived_tables"),
            patch("subprocess.run") as mock_subprocess,
        ):
            _postflight.run_auto("feat: test")

        # Confirm no 'aws sso login' call was made
        for call_args in mock_subprocess.call_args_list:
            cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("args", [])
            assert not ("sso" in cmd and "login" in cmd), f"Unexpected aws sso login call: {cmd}"

    def test_false_check_sso_skips_drain_without_error(self, capsys: pytest.CaptureFixture) -> None:
        """When check_sso returns False, drain is skipped and run_auto continues (skip-and-continue)."""
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.sync_ops.check_sso", return_value=False),
            patch("scripts.ops_data_portal.drain_pending") as mock_drain,
            patch("scripts.ops_data_portal.drain_pending_decisions") as mock_drain_dec,
            patch("session_postflight._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        # skip-and-continue: rc must be 0 (not a blocking error)
        assert rc == 0
        # drain must NOT be called when credentials are unavailable
        mock_drain.assert_not_called()
        mock_drain_dec.assert_not_called()
        # informational skip message emitted (not an ERROR)
        captured = capsys.readouterr()
        assert "skipping drain" in captured.out or "Credentials unavailable" in captured.out

    def test_true_check_sso_calls_drain(self, capsys: pytest.CaptureFixture) -> None:
        """When check_sso returns True, drain_pending is called normally."""
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 1, "skipped": 0}) as mock_drain,
            patch("scripts.ops_data_portal.drain_pending_decisions", return_value={"drained": 0}),
            patch("session_postflight._stage_document_derived_tables"),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0
        mock_drain.assert_called_once()


class TestStageDocumentDerivedTables:
    """Tests for _stage_document_derived_tables() (neutered in Phase 0+1)."""

    def test_is_noop_no_opswriter_call(self) -> None:
        """Neutered stub does not invoke OpsWriter (ETL bypass removed)."""
        with patch("scripts.ops_writer.OpsWriter") as mock_ow:
            _postflight._stage_document_derived_tables()
        mock_ow.assert_not_called()

    def test_does_not_raise(self) -> None:
        """Neutered stub completes without raising."""
        _postflight._stage_document_derived_tables()

    def test_does_not_raise_on_any_input(self, capsys: pytest.CaptureFixture) -> None:
        """Neutered stub ignores all context and does not raise."""
        _postflight._stage_document_derived_tables()

    def test_auto_mode_does_not_call_stage_documents(self, capsys: pytest.CaptureFixture) -> None:
        """run_auto() does not call _stage_document_derived_tables (ETL bypass removed)."""
        close_out = json.dumps(
            {
                "intent_achieved": True,
                "session_log_entry": "## [2026-04-28] session",
                "sanity_status": "PASS",
                "details": {},
            }
        )
        push_out = json.dumps({"status": "merged", "pr_url": "https://github.com/pr/1"})

        def fake_close() -> int:
            print(close_out)
            return 0

        def fake_push() -> int:
            print(push_out)
            return 0

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", side_effect=fake_close),
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("session_postflight._stage_document_derived_tables") as mock_stage,
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0
        mock_stage.assert_not_called()


class TestPruneTelemetryLogs:
    """Tests for prune_telemetry_logs and helpers."""

    def test_prune_moves_old_entries(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        archive = logs / "archive"
        old_line = json.dumps({"date": "2020-01-01", "msg": "old"})
        new_line = json.dumps({"date": "2099-12-31", "msg": "new"})
        (logs / ".test-log.jsonl").write_text(f"{old_line}\n{new_line}\n", encoding="utf-8")
        with (
            patch.object(_postflight, "LOGS_DIR", logs),
            patch.object(_postflight, "ARCHIVE_DIR", archive),
        ):
            result = _postflight.prune_telemetry_logs(max_age_days=90)
        assert ".test-log.jsonl" in result["pruned"]
        remaining = (logs / ".test-log.jsonl").read_text(encoding="utf-8")
        assert "2099-12-31" in remaining
        assert "2020-01-01" not in remaining
        archived = list(archive.glob("*.jsonl"))
        assert len(archived) == 1
        assert "2020-01-01" in archived[0].read_text(encoding="utf-8")

    def test_prune_skips_directories(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "archive").mkdir()
        (logs / "transcripts").mkdir()
        (logs / ".keep.jsonl").write_text(
            json.dumps({"date": "2099-01-01"}) + "\n",
            encoding="utf-8",
        )
        with (
            patch.object(_postflight, "LOGS_DIR", logs),
            patch.object(_postflight, "ARCHIVE_DIR", logs / "archive"),
        ):
            result = _postflight.prune_telemetry_logs(max_age_days=90)
        assert ".keep.jsonl" in result["skipped"]

    def test_prune_handles_no_logs_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        with patch.object(_postflight, "LOGS_DIR", missing):
            result = _postflight.prune_telemetry_logs(max_age_days=30)
        assert result == {"pruned": [], "skipped": []}

    def test_prune_uses_timestamp_field(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        archive = logs / "archive"
        old = json.dumps({"timestamp": "2020-06-15T12:00:00Z", "v": 1})
        new = json.dumps({"timestamp": "2099-06-15T12:00:00Z", "v": 2})
        (logs / ".ts-log.jsonl").write_text(f"{old}\n{new}\n", encoding="utf-8")
        with (
            patch.object(_postflight, "LOGS_DIR", logs),
            patch.object(_postflight, "ARCHIVE_DIR", archive),
        ):
            result = _postflight.prune_telemetry_logs(max_age_days=90)
        assert ".ts-log.jsonl" in result["pruned"]

    def test_prune_preserves_malformed_lines(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        archive = logs / "archive"
        bad_line = "NOT JSON"
        old = json.dumps({"date": "2020-01-01", "x": 1})
        (logs / ".bad.jsonl").write_text(f"{bad_line}\n{old}\n", encoding="utf-8")
        with (
            patch.object(_postflight, "LOGS_DIR", logs),
            patch.object(_postflight, "ARCHIVE_DIR", archive),
        ):
            result = _postflight.prune_telemetry_logs(max_age_days=90)
        assert ".bad.jsonl" in result["pruned"]
        remaining = (logs / ".bad.jsonl").read_text(encoding="utf-8")
        assert "NOT JSON" in remaining

    def test_load_max_age_days_default(self) -> None:
        with patch.object(_postflight, "ROOT", Path("/nonexistent")):
            val = _postflight._load_max_age_days()
        assert val == _postflight.DEFAULT_MAX_AGE_DAYS

    def test_load_max_age_days_from_yaml(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        cfg = config_dir / "config.yaml"
        cfg.write_text(
            "telemetry:\n  max_age_days: 45\n",
            encoding="utf-8",
        )
        with patch.object(_postflight, "ROOT", tmp_path):
            val = _postflight._load_max_age_days()
        assert val == 45

    def test_run_metrics_calls_prune(self, capsys: pytest.CaptureFixture) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{}"
        mock_result.stderr = ""
        with (
            patch(
                "session_postflight._run",
                return_value=mock_result,
            ),
            patch(
                "session_postflight.prune_telemetry_logs",
                return_value={
                    "pruned": ["a.jsonl"],
                    "skipped": [],
                },
            ) as mock_prune,
        ):
            rc = _postflight.run_metrics()
        assert rc == 0
        mock_prune.assert_called_once()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "telemetry_pruning" in data


# ---------------------------------------------------------------------------
# compact_all() integration in run_auto (Decision 50)
# ---------------------------------------------------------------------------


class TestRunAutoCompactAll:
    """Tests for ops_data_portal.sync() integration in run_auto (Decision 50)."""

    def test_compact_all_called_in_run_auto(self, capsys: pytest.CaptureFixture) -> None:
        """ops_data_portal.sync() is called after drain_pending in run_auto."""
        mock_sync = MagicMock(return_value=None)

        with (
            patch("session_postflight.run_validate", return_value=0),
            patch("session_postflight.run_close", return_value=0),
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", return_value=0),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
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
            patch("session_postflight.run_metrics", return_value=0),
            patch("session_postflight.run_commit", return_value=0),
            patch("session_postflight.run_push", side_effect=fake_push),
            patch("session_postflight.run_log_housekeeping", return_value=0),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0}),
            patch("scripts.ops_data_portal.sync", side_effect=ImportError("ops_data_portal not found")),
        ):
            rc = _postflight.run_auto("feat: test")

        assert rc == 0


# ---------------------------------------------------------------------------
# close_telemetry_session() tests
# ---------------------------------------------------------------------------


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
            with patch("session_postflight.TELEMETRY_ACTIVE_SESSION_FILE", state_file):
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
        with patch("session_postflight.TELEMETRY_ACTIVE_SESSION_FILE", missing):
            _postflight.close_telemetry_session(outcome="success")

        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "Skipping" in captured.err
