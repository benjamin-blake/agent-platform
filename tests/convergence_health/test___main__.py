"""Unit tests for scripts.convergence_health.__main__ (rec-2709 Wave 6 package-mirror).

CLI dispatch: python -m scripts.convergence_health [--ducklake-drift|--prod-drift].
"""

from __future__ import annotations

from unittest.mock import patch

# boto3 is imported at MODULE scope even though the tests reference it only via
# patch("boto3.Session") strings. This makes the file's heavy-dep requirement visible to the
# fast tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to the full
# post-merge tier, instead of catching it REACTIVELY -- which re-runs the entire changed-test set
# a second time after a runtime ModuleNotFoundError and roughly doubles the pytest cost. boto3 is
# deliberately excluded from requirements-fast.txt; the full tier runs this file. See
# scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401
import pytest

from scripts.convergence_health import HealthVerdict, main, main_ducklake_drift, main_prod_drift


class TestMain:
    def _verdict(self, status: str = "green") -> HealthVerdict:
        return HealthVerdict(status=status, red_age_hours=0.0, unapplied_backlog=0, severity="none")

    def test_main_happy_path_returns_zero(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.assess_health", return_value=self._verdict("green")),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}) as esc,
        ):
            rc = main(profile="agent_platform")
        assert rc == 0
        esc.assert_called_once()

    def test_main_red_path_escalates_and_returns_zero(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "red"}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.find_reconcile_runs_since", return_value=[]),
            patch("scripts.convergence_health.__main__.assess_health", return_value=self._verdict("red")),
            patch(
                "scripts.convergence_health.__main__.escalate",
                return_value={"action": "file", "rec_id": "rec-1"},
            ) as esc,
        ):
            rc = main()
        assert rc == 0
        esc.assert_called_once()

    def test_main_returns_one_on_s3_init_failure(self) -> None:
        with patch("boto3.Session", side_effect=RuntimeError("no creds")):
            rc = main()
        assert rc == 1

    def test_main_red_status_checks_reconcile_in_flight_and_passes_through(self) -> None:
        # A reconcile.yml run inside the episode window -> escalate() called with
        # reconcile_in_flight=True.
        with (
            patch("boto3.Session"),
            patch(
                "scripts.convergence_health.__main__.read_convergence_record",
                return_value={"status": "red", "timestamp": "2026-06-27T06:00:00Z"},
            ),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch(
                "scripts.convergence_health.__main__.find_reconcile_runs_since",
                return_value=[{"id": 1, "created_at": "2026-06-27T07:00:00Z"}],
            ) as find_reconcile,
            patch("scripts.convergence_health.__main__.assess_health", return_value=self._verdict("red")),
            patch(
                "scripts.convergence_health.__main__.escalate",
                return_value={"action": "skipped_reconcile_in_flight", "rec_id": None},
            ) as esc,
        ):
            rc = main()
        assert rc == 0
        find_reconcile.assert_called_once()
        assert esc.call_args.kwargs["reconcile_in_flight"] is True

    def test_main_green_status_skips_reconcile_lookup_entirely(self) -> None:
        # No red episode -> no reason to spend the extra GitHub API call.
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.find_reconcile_runs_since") as find_reconcile,
            patch("scripts.convergence_health.__main__.assess_health", return_value=self._verdict("green")),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}) as esc,
        ):
            rc = main()
        assert rc == 0
        find_reconcile.assert_not_called()
        assert esc.call_args.kwargs["reconcile_in_flight"] is False

    def test_main_prints_pending_gated_in_verdict_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """DEP-11 (T2.47): the printed HealthVerdict JSON must include pending_gated so the
        convergence-health sensor surfaces a routed-pending episode."""
        marker = {"routed_at": "2026-06-27T00:00:00Z", "run_url": "https://example.com/run/1", "commit_sha": "abc123"}
        verdict = HealthVerdict(
            status="green",
            red_age_hours=0.0,
            unapplied_backlog=0,
            severity="none",
            pending_gated=marker,
        )
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.assess_health", return_value=verdict),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        assert "pending_gated" in captured.out
        assert "abc123" in captured.out

    def test_main_prints_pending_gated_null_when_absent(self, capsys: pytest.CaptureFixture[str]) -> None:
        verdict = self._verdict("green")
        assert verdict.pending_gated is None
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.assess_health", return_value=verdict),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        assert '"pending_gated": null' in captured.out

    def test_main_absent_record_skips_reconcile_lookup(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value=None),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.__main__.find_reconcile_runs_since") as find_reconcile,
            patch("scripts.convergence_health.__main__.assess_health", return_value=self._verdict("unknown")),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        find_reconcile.assert_not_called()


class TestMainDiagnoseMode:
    def test_diagnose_mode_does_not_call_escalate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONVERGENCE_HEALTH_DIAGNOSE", "1")
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.diagnose_stuck_approvals", return_value=[]),
            patch(
                "scripts.convergence_health.__main__.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.__main__.escalate") as esc,
        ):
            rc = main()
        assert rc == 0
        esc.assert_not_called()

    def test_diagnose_mode_calls_diagnose_stuck_approvals_not_find_stuck(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONVERGENCE_HEALTH_DIAGNOSE", "1")
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.diagnose_stuck_approvals", return_value=[]) as diag,
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals") as find_stuck,
            patch(
                "scripts.convergence_health.__main__.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.__main__.escalate"),
        ):
            main()
        diag.assert_called_once()
        find_stuck.assert_not_called()

    def test_normal_mode_calls_find_stuck_not_diagnose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONVERGENCE_HEALTH_DIAGNOSE", raising=False)
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.__main__.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.__main__.find_stuck_gated_approvals", return_value=[]) as find_stuck,
            patch("scripts.convergence_health.__main__.diagnose_stuck_approvals") as diag,
            patch(
                "scripts.convergence_health.__main__.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.__main__.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        find_stuck.assert_called_once()
        diag.assert_not_called()


class TestMainDucklakeDrift:
    def test_happy_path_returns_zero(self) -> None:
        with patch(
            "scripts.convergence_health.__main__.detect_ducklake_code_drift",
            return_value={"action": "none", "rec_id": None},
        ) as detect:
            rc = main_ducklake_drift(profile="agent_platform")
        assert rc == 0
        detect.assert_called_once_with(profile="agent_platform")

    def test_exception_returns_one(self) -> None:
        with patch(
            "scripts.convergence_health.__main__.detect_ducklake_code_drift",
            side_effect=RuntimeError("boom"),
        ):
            rc = main_ducklake_drift()
        assert rc == 1


class TestMainProdDrift:
    def test_happy_path_returns_zero(self) -> None:
        with patch(
            "scripts.convergence_health.__main__.detect_prod_code_drift",
            return_value={"action": "none", "rec_id": None},
        ) as detect:
            rc = main_prod_drift(profile="agent_platform")
        assert rc == 0
        detect.assert_called_once_with(profile="agent_platform")

    def test_exception_returns_one(self) -> None:
        with patch(
            "scripts.convergence_health.__main__.detect_prod_code_drift",
            side_effect=RuntimeError("boom"),
        ):
            rc = main_prod_drift()
        assert rc == 1
