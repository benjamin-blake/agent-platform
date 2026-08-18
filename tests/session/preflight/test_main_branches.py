"""main()-branch coverage for a handful of edge paths that predate this plan and were never
exercised through the officially-mapped tests/session/preflight/ package (only through the
separate tests/test_session_preflight_decomposition.py equivalence suite, which
scripts.test_coverage_checker's map_source_to_test does not include in preflight.py's coverage
run): the wrong-venv CRITICAL branch, the log-sync-committed uncommitted-flag clear, the
terraform_pending tuple-unpack branch, the outbox non-empty/exception paths, the warm_sync
exception path, and the PYTEST_CURRENT_TEST-absent S3_LOG_BUCKET default. New in
PLAN-convergence-health-prod-drift-red -- touching scripts/session/preflight.py for the
convergence-sensor-liveness wiring pushed the file's coverage measurement into failing territory,
surfacing this pre-existing gap (Decision 128/102 decompose-by-default: a new file rather than
growing the already near-budget test_main_report.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestPytestCurrentTestAbsent:
    def test_s3_log_bucket_defaulted_when_pytest_current_test_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When PYTEST_CURRENT_TEST is absent (a real, non-test invocation), main() defaults
        S3_LOG_BUCKET so downstream log-storage calls have a bucket to target.

        main()'s own os.environ.setdefault(...) call is an UNTRACKED mutation from
        monkeypatch's perspective (monkeypatch.delenv on an already-absent key registers no
        undo action, since it never touched anything) -- a bare monkeypatch.delenv setup with
        no explicit teardown here would leak S3_LOG_BUCKET into every later test in this
        process (scripts.s3_log_store.get_backend() then reports "s3" instead of "local"
        repo-wide). The try/finally below is the deliberate, explicit cleanup.
        """
        preflight_report = tmp_path / ".preflight-report.json"
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        try:
            with (
                patch("scripts.preflight.env_git.check_venv", return_value=True),
                patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
                patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
                patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
                patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
                patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
                patch("scripts.preflight.context_docs.read_context_files", return_value={}),
                patch(
                    "scripts.preflight.context_docs.check_telemetry_health",
                    return_value={"overall": "ok", "checks": [], "friction_patterns": []},
                ),
                patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
                patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
                patch("scripts.sync.ops.outbox_summary", return_value={}),
                # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
                # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
                # recommendation) are irrelevant to what this test asserts; mocking them keeps this
                # new file from inheriting that cost for behavior it doesn't exercise.
                patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
                patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
                patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
                patch("builtins.print"),
            ):
                _preflight.main()
            assert os.environ.get("S3_LOG_BUCKET") == "agent-platform-data-lake"
        finally:
            os.environ.pop("S3_LOG_BUCKET", None)


class TestWrongVenvCriticalBranch:
    def test_wrong_venv_prints_critical_and_activate_hint(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        printed: list[str] = []

        def _capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with (
            patch("scripts.preflight.env_git.check_venv", return_value=False),
            patch("scripts.preflight.env_git._print_activate_hint") as mock_hint,
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", return_value={}),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print", side_effect=_capture),
        ):
            exit_code = _preflight.main()
        assert exit_code == 1
        mock_hint.assert_called_once()
        assert any("CRITICAL: Wrong virtual environment" in line for line in printed)


class TestLogSyncCommittedClearsUncommitted:
    def test_committed_log_sync_clears_uncommitted_flag(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch(
                "scripts.preflight.env_git.run_log_sync",
                return_value={"status": "committed", "files": ["logs/.session-log.md"]},
            ),
            # get_git_status reports dirty (True); the committed log-sync result must override it.
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", True, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", return_value={}),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert report["uncommitted_changes"] is False


class TestTerraformPendingTupleUnpack:
    def test_tuple_result_unpacks_terraform_pending_and_convergence_health(self, tmp_path: Path) -> None:
        """check_terraform_pending's documented return shape is (bool|None, dict|None) -- a real
        tuple, not the bare bool most other tests in this package stub it to."""
        preflight_report = tmp_path / ".preflight-report.json"
        convergence_health = {"status": "green", "red_age_hours": 0.0, "unapplied_backlog": 0, "stuck_approvals": 0}
        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch(
                "scripts.preflight.aws_infra.check_terraform_pending",
                return_value=(True, convergence_health),
            ),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", return_value={}),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert report["terraform_pending"] is True
        assert report["convergence_health"] == convergence_health


class TestOpsOutboxPaths:
    def _run(self, tmp_path: Path, outbox_summary_kwargs: dict) -> tuple[dict, list[str]]:
        preflight_report = tmp_path / ".preflight-report.json"
        printed: list[str] = []

        def _capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", **outbox_summary_kwargs),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print", side_effect=_capture),
        ):
            _preflight.main()
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
        return report, printed

    def test_non_empty_outbox_prints_pending_entries(self, tmp_path: Path) -> None:
        report, printed = self._run(tmp_path, {"return_value": {"ops_recommendations_pending": 3}})
        assert report["ops_outbox"] == {"ops_recommendations_pending": 3}
        assert any("Ops outbox: 3 pending entries" in line for line in printed)

    def test_outbox_summary_exception_degrades_to_empty(self, tmp_path: Path) -> None:
        report, _ = self._run(tmp_path, {"side_effect": RuntimeError("outbox unreachable")})
        assert report["ops_outbox"] == {}


class TestWarmSyncExceptionWhenCredsOk:
    def test_warm_sync_exception_does_not_crash_main(self, tmp_path: Path) -> None:
        """creds_status == 'ok' takes the warm_sync branch; a raised exception there is
        best-effort and must not propagate out of main()."""
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="ok"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", return_value={}),
            patch("scripts.sync.ops.warm_sync", side_effect=RuntimeError("neon unreachable")),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            exit_code = _preflight.main()
        assert exit_code == 0
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert report["creds_status"] == "ok"
        # warm_sync's exception is swallowed -- recommendation_sync stays at its pre-warm-up default.
        assert report["recommendation_sync"] == {}


class TestProvisionalContractsEmpty:
    def test_no_provisional_contracts_due_prints_none(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        printed: list[str] = []

        def _capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="unavailable"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("scripts.preflight.context_docs.read_context_files", return_value={}),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._check_convergence_sensor_liveness", return_value=None),
            patch("scripts.sync.ops.outbox_summary", return_value={}),
            patch("scripts.preflight.context_docs._scan_provisional_contracts", return_value=[]),
            # Real compute_state_dict() calls (~7-10s each, unmocked in most of this package's
            # sibling main()-level tests -- a pre-existing, repo-wide cost filed as a
            # recommendation) are irrelevant to what this test asserts; mocking them keeps this
            # new file from inheriting that cost for behavior it doesn't exercise.
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value={}),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print", side_effect=_capture),
        ):
            _preflight.main()
        output = "\n".join(printed)
        assert "--- Provisional contracts due ---" in output
        assert "  (none)" in printed


class TestOpenTelemetrySessionFallback:
    def test_open_session_exception_falls_back_to_local_uuid(self, tmp_path: Path) -> None:
        """open_telemetry_session() must never raise -- a telemetry backend failure degrades to
        a locally-generated UUID so the calling workflow (e.g. /implement Step 1) can proceed."""
        active_session_file = tmp_path / ".telemetry-active-session.json"
        with (
            patch("scripts.executor.telemetry.open_session", side_effect=RuntimeError("telemetry backend down")),
            patch("session_preflight.TELEMETRY_ACTIVE_SESSION_FILE", active_session_file),
        ):
            session_id = _preflight.open_telemetry_session(workflow="implement", branch="claude/test")
        assert session_id
        # A valid UUID4 string (36 chars, hyphenated) -- the fallback path's own generated id.
        assert len(session_id) == 36
        assert session_id.count("-") == 4
        assert json.loads(active_session_file.read_text(encoding="utf-8"))["session_id"] == session_id
