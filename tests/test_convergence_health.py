"""Unit tests for scripts.convergence_health.

All tests are free of live AWS, git, and network dependencies:
S3 client, git runner, GitHub API caller, and portal caller are injected.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch

# boto3 is imported at MODULE scope even though the tests reference it only via
# patch("boto3.Session") strings. This makes the file's heavy-dep requirement visible to the
# fast tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to the full
# post-merge tier, instead of catching it REACTIVELY -- which re-runs the entire changed-test set
# a second time after a runtime ModuleNotFoundError and roughly doubles the pytest cost. boto3 is
# deliberately excluded from requirements-fast.txt; the full tier runs this file. See
# scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401
import pytest

import scripts.convergence_health as ch
from scripts.build_lambda_config import (
    _DUCKLAKE_CATALOG_DR_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_WRITER_FUNCTION,
)
from scripts.convergence_health import (
    HealthVerdict,
    _make_github_caller,
    assess_health,
    count_unapplied_tf_commits,
    derive_red_since,
    detect_ducklake_code_drift,
    diagnose_stuck_approvals,
    escalate,
    escalation_action,
    filter_stuck_runs,
    find_open_convergence_stale_rec,
    find_open_ducklake_drift_rec,
    find_reconcile_runs_since,
    find_stuck_gated_approvals,
    has_in_flight_reconcile_for_episode,
    main,
    main_ducklake_drift,
    read_convergence_record,
    red_age_hours,
)

# ---------------------------------------------------------------------------
# derive_red_since
# ---------------------------------------------------------------------------


class TestDeriveRedSince:
    def test_uses_drift_detected_at_when_present(self) -> None:
        rec = {
            "status": "red",
            "timestamp": "2026-06-24T22:09:58Z",
            "drift_detected_at": "2026-06-26T11:52:07Z",
        }
        rs = derive_red_since(rec)
        assert rs.isoformat().startswith("2026-06-26"), rs

    def test_falls_back_to_timestamp_when_no_drift_detected_at(self) -> None:
        rec = {"status": "red", "timestamp": "2026-06-24T22:09:58Z"}
        rs = derive_red_since(rec)
        assert rs.isoformat().startswith("2026-06-24"), rs

    def test_empty_record_returns_epoch(self) -> None:
        rs = derive_red_since({})
        assert rs == datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# red_age_hours
# ---------------------------------------------------------------------------


class TestRedAgeHours:
    def test_red_age_boundary_exceeds_threshold(self) -> None:
        rec = {
            "status": "red",
            "timestamp": "2026-06-24T22:09:58Z",
            "drift_detected_at": "2026-06-26T11:52:07Z",
        }
        now = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)
        age = red_age_hours(rec, now=now)
        assert age > 6, f"expected age > 6h, got {age}"

    def test_returns_zero_for_green_record(self) -> None:
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z"}
        assert red_age_hours(rec) == 0.0

    def test_returns_zero_for_unknown_status(self) -> None:
        rec = {"status": "unknown", "timestamp": "2026-06-27T00:00:00Z"}
        assert red_age_hours(rec) == 0.0

    def test_under_threshold(self) -> None:
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
        }
        now = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        age = red_age_hours(rec, now=now)
        assert age == pytest.approx(3.0, abs=0.01)


# ---------------------------------------------------------------------------
# count_unapplied_tf_commits
# ---------------------------------------------------------------------------


class TestCountUnappliedTfCommits:
    def test_counts_commits_from_mocked_git_log(self) -> None:
        output = "abc1234 feat: add bucket\ndef5678 fix: policy update"
        runner = lambda cmd: output  # noqa: E731
        assert count_unapplied_tf_commits("deadbeef", git_runner=runner) == 2

    def test_returns_zero_when_no_commits(self) -> None:
        runner = lambda cmd: ""  # noqa: E731
        assert count_unapplied_tf_commits("deadbeef", git_runner=runner) == 0

    def test_returns_zero_on_empty_sha(self) -> None:
        assert count_unapplied_tf_commits("") == 0

    def test_returns_zero_on_git_exception(self) -> None:
        def _fail(cmd: list[str]) -> str:
            raise RuntimeError("git not available")

        assert count_unapplied_tf_commits("abc123", git_runner=_fail) == 0


# ---------------------------------------------------------------------------
# escalation_action
# ---------------------------------------------------------------------------


class TestEscalationAction:
    def test_file_when_over_threshold_and_no_rec(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=False) == "file"

    def test_update_when_over_threshold_and_rec_exists(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=True) == "update"

    def test_close_when_under_threshold_and_rec_exists(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=True) == "close"

    def test_none_when_under_threshold_and_no_rec(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=False) == "none"


# ---------------------------------------------------------------------------
# find_open_convergence_stale_rec
# ---------------------------------------------------------------------------


class TestFindOpenConvergenceStaleRec:
    def test_returns_first_matching_rec(self) -> None:
        recs = [
            {"id": "rec-100", "source": "ci_rca", "status": "open"},
            {"id": "rec-101", "source": "tf_convergence_stale", "status": "open"},
            {"id": "rec-102", "source": "tf_convergence_stale", "status": "closed"},
        ]
        result = find_open_convergence_stale_rec(recs)
        assert result is not None
        assert result["id"] == "rec-101"

    def test_returns_none_when_no_match(self) -> None:
        recs = [
            {"id": "rec-100", "source": "ci_rca", "status": "open"},
            {"id": "rec-101", "source": "tf_convergence_stale", "status": "closed"},
        ]
        assert find_open_convergence_stale_rec(recs) is None

    def test_returns_none_on_empty_list(self) -> None:
        assert find_open_convergence_stale_rec([]) is None


# ---------------------------------------------------------------------------
# assess_health
# ---------------------------------------------------------------------------


class TestAssessHealth:
    def test_unknown_verdict_when_record_is_none(self) -> None:
        v = assess_health(None)
        assert v.status == "unknown"
        assert v.severity == "none"

    def test_high_severity_when_red_over_threshold(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        rec = {
            "status": "red",
            "timestamp": "2026-06-24T22:09:58Z",
            "drift_detected_at": "2026-06-26T11:52:07Z",
            "commit_sha": "",
        }
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.status == "red"
        assert v.severity == "high"
        assert v.red_age_hours > 6

    def test_low_severity_when_red_under_threshold(self) -> None:
        now = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
            "commit_sha": "",
        }
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.status == "red"
        assert v.severity == "low"
        assert v.red_age_hours < 6

    def test_high_severity_when_stuck_approvals_present(self) -> None:
        now = datetime(2026, 6, 27, 4, 0, tzinfo=timezone.utc)
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
            "commit_sha": "",
        }
        stuck = [{"run_id": 12345, "age_hours": 7.5, "url": "https://example.com"}]
        v = assess_health(rec, stuck_approvals=stuck, git_runner=lambda cmd: "", now=now)
        assert v.severity == "high"
        assert len(v.stuck_approvals) == 1

    def test_none_severity_for_green_record(self) -> None:
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": ""}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.severity == "none"

    def test_unapplied_backlog_counted(self) -> None:
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
            "commit_sha": "abc123",
        }
        git_output = "commit1 msg\ncommit2 msg\ncommit3 msg"
        v = assess_health(rec, git_runner=lambda cmd: git_output)
        assert v.unapplied_backlog == 3


# ---------------------------------------------------------------------------
# escalate (idempotent file / update / close -- mocked portal)
# ---------------------------------------------------------------------------


class TestEscalate:
    def _make_verdict(self, red_age: float = 10.0, status: str = "red") -> HealthVerdict:
        return HealthVerdict(
            status=status,
            red_age_hours=red_age,
            unapplied_backlog=2,
            stuck_approvals=[],
            severity="high" if red_age >= 6 else "low",
        )

    def test_files_rec_when_over_threshold_and_no_open_rec(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-999"

        verdict = self._make_verdict(red_age=10.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[])
        assert result["action"] == "file"
        assert result["rec_id"] == "rec-999"
        assert calls[0][0] == "file"
        assert calls[0][1]["source"] == "tf_convergence_stale"
        assert calls[0][1]["priority"] == "High"

    def test_updates_when_over_threshold_and_open_rec_exists(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-888", "source": "tf_convergence_stale", "status": "open"}
        verdict = self._make_verdict(red_age=10.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing])
        assert result["action"] == "update"
        assert result["rec_id"] == "rec-888"
        assert calls[0][0] == "update"

    def test_closes_when_under_threshold_and_open_rec_exists(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-777", "source": "tf_convergence_stale", "status": "open"}
        verdict = self._make_verdict(red_age=2.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing])
        assert result["action"] == "close"
        assert result["rec_id"] == "rec-777"
        assert calls[0][0] == "close"

    def test_no_action_when_under_threshold_and_no_rec(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        verdict = self._make_verdict(red_age=2.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[])
        assert result["action"] == "none"
        assert not calls

    def test_no_rec_filed_when_status_is_green(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        verdict = HealthVerdict(
            status="green",
            red_age_hours=0.0,
            unapplied_backlog=0,
            stuck_approvals=[],
            severity="none",
        )
        result = escalate(verdict, portal_caller=_caller, open_recs=[])
        assert result["action"] == "none"
        assert not calls

    def test_stuck_approval_triggers_escalation_below_age_threshold(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-555"

        verdict = HealthVerdict(
            status="red",
            red_age_hours=3.0,
            unapplied_backlog=0,
            stuck_approvals=[{"run_id": 1, "age_hours": 8.0, "url": "https://example.com"}],
            severity="high",
        )
        result = escalate(verdict, portal_caller=_caller, open_recs=[], threshold_hours=6.0)
        assert result["action"] == "file"

    def test_dedup_second_tick_updates_not_files(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-444", "source": "tf_convergence_stale", "status": "open"}
        verdict = self._make_verdict(red_age=12.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing])
        assert result["action"] == "update"
        assert len(calls) == 1
        assert calls[0][0] == "update"


# ---------------------------------------------------------------------------
# escalate() reconcile_in_flight suppression (T2.37 c4)
# ---------------------------------------------------------------------------


class TestEscalateReconcileInFlight:
    def _make_verdict(self, red_age: float = 10.0, status: str = "red") -> HealthVerdict:
        return HealthVerdict(
            status=status,
            red_age_hours=red_age,
            unapplied_backlog=0,
            stuck_approvals=[],
            severity="high" if red_age >= 6 else "low",
        )

    def test_does_not_double_file_when_reconcile_in_flight(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-999"

        verdict = self._make_verdict(red_age=10.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[], reconcile_in_flight=True)
        assert result["action"] == "skipped_reconcile_in_flight"
        assert result["rec_id"] is None
        assert not calls, "must not file a rec while a Reconcile run is in-flight for this episode"

    def test_files_normally_when_reconcile_not_in_flight(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-999"

        verdict = self._make_verdict(red_age=10.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[], reconcile_in_flight=False)
        assert result["action"] == "file"
        assert calls

    def test_reconcile_in_flight_does_not_suppress_update_of_existing_rec(self) -> None:
        # Suppression applies ONLY to a fresh "file" -- an already-open rec still updates (not a
        # double-file; it's the same rec being refreshed).
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-888", "source": "tf_convergence_stale", "status": "open"}
        verdict = self._make_verdict(red_age=10.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing], reconcile_in_flight=True)
        assert result["action"] == "update"
        assert result["rec_id"] == "rec-888"

    def test_reconcile_in_flight_does_not_suppress_close(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-777", "source": "tf_convergence_stale", "status": "open"}
        verdict = self._make_verdict(red_age=2.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing], reconcile_in_flight=True)
        assert result["action"] == "close"

    def test_reconcile_in_flight_irrelevant_when_under_threshold(self) -> None:
        verdict = self._make_verdict(red_age=2.0)
        result = escalate(verdict, portal_caller=lambda a, f: None, open_recs=[], reconcile_in_flight=True)
        assert result["action"] == "none"


# ---------------------------------------------------------------------------
# find_reconcile_runs_since / has_in_flight_reconcile_for_episode (T2.37 c4)
# ---------------------------------------------------------------------------


class TestFindReconcileRunsSince:
    def test_returns_workflow_runs_list(self) -> None:
        mock_data = {
            "workflow_runs": [
                {"id": 1, "created_at": "2026-06-27T06:00:00Z"},
                {"id": 2, "created_at": "2026-06-27T07:00:00Z"},
            ]
        }
        result = find_reconcile_runs_since(gh_caller=lambda url: mock_data)
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_url_targets_reconcile_workflow(self) -> None:
        captured: list[str] = []

        def _capture(url: str) -> Any:
            captured.append(url)
            return {"workflow_runs": []}

        find_reconcile_runs_since(gh_caller=_capture)
        assert captured
        assert "reconcile.yml/runs" in captured[0]
        # Deliberately no status= filter -- any status counts as "in-flight/recent" (T2.37 c4).
        assert "status=" not in captured[0]

    def test_returns_empty_when_caller_returns_none(self) -> None:
        assert find_reconcile_runs_since(gh_caller=lambda url: None) == []

    def test_swallows_caller_exception(self) -> None:
        def _boom(url: str) -> Any:
            raise RuntimeError("api down")

        assert find_reconcile_runs_since(gh_caller=_boom) == []

    def test_no_token_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert find_reconcile_runs_since() == []

    def test_missing_workflow_runs_key_returns_empty(self) -> None:
        assert find_reconcile_runs_since(gh_caller=lambda url: {}) == []


class TestHasInFlightReconcileForEpisode:
    def test_run_created_after_red_since_is_in_flight(self) -> None:
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
        runs = [{"id": 1, "created_at": "2026-06-27T07:00:00Z"}]
        assert has_in_flight_reconcile_for_episode(runs, red_since=red_since, now=now) is True

    def test_run_created_before_red_since_is_not_in_flight(self) -> None:
        # A reconcile run from a PRIOR (already-resolved) episode must not suppress escalation
        # for a NEW red episode -- not matched by head_sha, matched purely by the time window.
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
        runs = [{"id": 1, "created_at": "2026-06-26T23:00:00Z"}]
        assert has_in_flight_reconcile_for_episode(runs, red_since=red_since, now=now) is False

    def test_no_runs_is_not_in_flight(self) -> None:
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        assert has_in_flight_reconcile_for_episode([], red_since=red_since) is False

    def test_run_missing_created_at_is_skipped(self) -> None:
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
        runs = [{"id": 1}]
        assert has_in_flight_reconcile_for_episode(runs, red_since=red_since, now=now) is False

    def test_run_exactly_at_red_since_counts_as_in_flight(self) -> None:
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
        runs = [{"id": 1, "created_at": "2026-06-27T06:00:00Z"}]
        assert has_in_flight_reconcile_for_episode(runs, red_since=red_since, now=now) is True

    def test_defaults_now_to_current_time(self) -> None:
        # now=None path -- exercised without mocking datetime.now; just assert it doesn't raise
        # and a run from far in the past (well before "red_since") is correctly excluded.
        red_since = datetime(2026, 6, 27, 6, 0, tzinfo=timezone.utc)
        runs = [{"id": 1, "created_at": "2020-01-01T00:00:00Z"}]
        assert has_in_flight_reconcile_for_episode(runs, red_since=red_since) is False


# ---------------------------------------------------------------------------
# read_convergence_record
# ---------------------------------------------------------------------------


class TestReadConvergenceRecord:
    def test_returns_parsed_json(self) -> None:
        import io
        import json

        payload = json.dumps({"status": "green", "commit_sha": "abc"}).encode()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(payload)}
        result = read_convergence_record(mock_s3)
        assert result == {"status": "green", "commit_sha": "abc"}

    def test_returns_none_on_no_such_key(self) -> None:
        from botocore.exceptions import ClientError

        error = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "not found"}},
            "GetObject",
        )
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = error
        assert read_convergence_record(mock_s3) is None


# ---------------------------------------------------------------------------
# find_stuck_gated_approvals
# ---------------------------------------------------------------------------


class TestFindStuckGatedApprovals:
    def test_returns_runs_over_threshold(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        mock_data = {
            "workflow_runs": [
                {
                    "id": 12345,
                    "created_at": "2026-06-27T06:00:00Z",
                    "html_url": "https://github.com/example/runs/12345",
                },
            ]
        }

        def _caller(url: str) -> Any:
            return mock_data

        result = find_stuck_gated_approvals(gh_caller=_caller, threshold_hours=6.0, now=now)
        assert len(result) == 1
        assert result[0]["run_id"] == 12345
        assert result[0]["age_hours"] >= 6.0

    def test_excludes_runs_under_threshold(self) -> None:
        now = datetime(2026, 6, 27, 7, 0, tzinfo=timezone.utc)
        mock_data = {
            "workflow_runs": [
                {
                    "id": 99999,
                    "created_at": "2026-06-27T06:00:00Z",
                    "html_url": "https://github.com/example/runs/99999",
                },
            ]
        }

        def _caller(url: str) -> Any:
            return mock_data

        result = find_stuck_gated_approvals(gh_caller=_caller, threshold_hours=6.0, now=now)
        assert result == []

    def test_returns_empty_when_caller_returns_none(self) -> None:
        result = find_stuck_gated_approvals(gh_caller=lambda url: None)
        assert result == []


class TestReadConvergenceRecordReraise:
    def test_non_nosuchkey_error_propagates(self) -> None:
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
        s3 = MagicMock()
        s3.get_object.side_effect = err
        with pytest.raises(ClientError):
            read_convergence_record(s3)


class TestEscalateGreenClosesOpenRec:
    """Acceptance criterion 3: a green record with an open rec closes that rec."""

    def test_green_status_with_open_rec_closes(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-555", "source": "tf_convergence_stale", "status": "open"}
        verdict = HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none")
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing])
        assert result["action"] == "close"
        assert result["rec_id"] == "rec-555"
        assert calls[0][0] == "close"


class TestFetchOpenRecs:
    def test_fetches_via_named_open_recs_verb(self) -> None:
        reader = MagicMock()
        reader.named.return_value = [{"id": "rec-1", "source": "tf_convergence_stale", "status": "open"}]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader) as mk:
            result = ch._fetch_open_recs(profile="agent_platform")
        mk.assert_called_once_with(profile="agent_platform")
        reader.named.assert_called_once_with("open_recs")
        assert result[0]["id"] == "rec-1"

    def test_returns_empty_list_when_verb_returns_none(self) -> None:
        reader = MagicMock()
        reader.named.return_value = None
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = ch._fetch_open_recs()
        assert result == []


class TestCountUnappliedTfCommitsDefaultRunner:
    def test_default_runner_counts_commit_lines(self) -> None:
        completed = MagicMock(returncode=0, stdout="abc123\ndef456\n")
        with patch("scripts.convergence_health.subprocess.run", return_value=completed):
            assert count_unapplied_tf_commits("sha0") == 2

    def test_default_runner_returns_zero_on_failure(self) -> None:
        with patch("scripts.convergence_health.subprocess.run", side_effect=OSError("git missing")):
            assert count_unapplied_tf_commits("sha0") == 0


class TestMain:
    def _verdict(self, status: str = "green") -> HealthVerdict:
        return HealthVerdict(status=status, red_age_hours=0.0, unapplied_backlog=0, severity="none")

    def test_main_happy_path_returns_zero(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value={}),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.assess_health", return_value=self._verdict("green")),
            patch("scripts.convergence_health.escalate", return_value={"action": "none", "rec_id": None}) as esc,
        ):
            rc = main(profile="agent_platform")
        assert rc == 0
        esc.assert_called_once()

    def test_main_red_path_escalates_and_returns_zero(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value={"status": "red"}),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.find_reconcile_runs_since", return_value=[]),
            patch("scripts.convergence_health.assess_health", return_value=self._verdict("red")),
            patch(
                "scripts.convergence_health.escalate",
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
                "scripts.convergence_health.read_convergence_record",
                return_value={"status": "red", "timestamp": "2026-06-27T06:00:00Z"},
            ),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]),
            patch(
                "scripts.convergence_health.find_reconcile_runs_since",
                return_value=[{"id": 1, "created_at": "2026-06-27T07:00:00Z"}],
            ) as find_reconcile,
            patch("scripts.convergence_health.assess_health", return_value=self._verdict("red")),
            patch(
                "scripts.convergence_health.escalate", return_value={"action": "skipped_reconcile_in_flight", "rec_id": None}
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
            patch("scripts.convergence_health.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.find_reconcile_runs_since") as find_reconcile,
            patch("scripts.convergence_health.assess_health", return_value=self._verdict("green")),
            patch("scripts.convergence_health.escalate", return_value={"action": "none", "rec_id": None}) as esc,
        ):
            rc = main()
        assert rc == 0
        find_reconcile.assert_not_called()
        assert esc.call_args.kwargs["reconcile_in_flight"] is False

    def test_main_absent_record_skips_reconcile_lookup(self) -> None:
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value=None),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]),
            patch("scripts.convergence_health.find_reconcile_runs_since") as find_reconcile,
            patch("scripts.convergence_health.assess_health", return_value=self._verdict("unknown")),
            patch("scripts.convergence_health.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        find_reconcile.assert_not_called()


class TestEscalateLiveFetchAndPortal:
    """Cover the production paths: live open-recs fetch and the real ops-portal calls."""

    def _verdict(self, status: str = "red", red_age: float = 10.0) -> HealthVerdict:
        return HealthVerdict(status=status, red_age_hours=red_age, unapplied_backlog=0, severity="high")

    def test_escalate_fetches_open_recs_when_not_injected(self) -> None:
        with (
            patch("scripts.convergence_health._fetch_open_recs", return_value=[]) as fetch,
            patch("scripts.ops_data_portal.file_rec", return_value="rec-live") as fr,
        ):
            result = escalate(self._verdict())
        fetch.assert_called_once()
        fr.assert_called_once()
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_escalate_update_uses_real_portal_when_no_caller(self) -> None:
        existing = {"id": "rec-200", "source": "tf_convergence_stale", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = escalate(self._verdict(), open_recs=[existing])
        ur.assert_called_once()
        assert result == {"action": "update", "rec_id": "rec-200"}

    def test_escalate_close_uses_real_portal_when_no_caller(self) -> None:
        existing = {"id": "rec-300", "source": "tf_convergence_stale", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = escalate(self._verdict(status="green", red_age=0.0), open_recs=[existing])
        ur.assert_called_once()
        assert result == {"action": "close", "rec_id": "rec-300"}


class TestFindStuckDefaultCaller:
    def test_no_token_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert find_stuck_gated_approvals() == []

    def test_skips_run_with_blank_created_at(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        data = {"workflow_runs": [{"id": 1, "created_at": "", "html_url": "u"}]}
        assert find_stuck_gated_approvals(gh_caller=lambda url: data, now=now) == []

    def test_swallows_caller_exception(self) -> None:
        def _boom(url: str) -> Any:
            raise RuntimeError("api down")

        assert find_stuck_gated_approvals(gh_caller=_boom) == []

    def test_default_caller_makes_authenticated_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "tok-abc")
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        payload = json.dumps({"workflow_runs": [{"id": 7, "created_at": "2026-06-27T06:00:00Z", "html_url": "u"}]}).encode()

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch("urllib.request.urlopen", return_value=_Resp()) as uo:
            result = find_stuck_gated_approvals(now=now)
        uo.assert_called_once()
        assert result[0]["run_id"] == 7


# ---------------------------------------------------------------------------
# _make_github_caller
# ---------------------------------------------------------------------------


class TestMakeGithubCaller:
    def test_empty_token_caller_returns_none(self) -> None:
        caller = _make_github_caller("")
        assert caller("https://api.github.com/test") is None

    def test_caller_with_token_makes_authenticated_request(self) -> None:
        payload = json.dumps({"workflow_runs": []}).encode()

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch("urllib.request.urlopen", return_value=_Resp()) as uo:
            caller = _make_github_caller("tok-xyz")
            result = caller("https://api.github.com/repos/o/r/actions/workflows/w/runs")
        uo.assert_called_once()
        req = uo.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer tok-xyz"
        assert result == {"workflow_runs": []}


# ---------------------------------------------------------------------------
# filter_stuck_runs
# ---------------------------------------------------------------------------


class TestFilterStuckRuns:
    def test_partitions_mixed_age_runs_by_threshold(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        runs = [
            {"id": 1, "created_at": "2026-06-27T06:00:00Z", "html_url": "u1"},  # age=14h
            {"id": 2, "created_at": "2026-06-27T19:00:00Z", "html_url": "u2"},  # age=1h
        ]
        result = filter_stuck_runs(runs, threshold_hours=6.0, now=now)
        assert [r["run_id"] for r in result] == [1]
        assert result[0]["age_hours"] >= 6.0
        assert result[0]["url"] == "u1"
        assert result[0]["created_at"] == "2026-06-27T06:00:00Z"

    def test_boundary_exactly_at_threshold_is_included(self) -> None:
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        runs = [{"id": 5, "created_at": "2026-06-27T06:00:00Z", "html_url": "u5"}]  # age=6.0h
        result = filter_stuck_runs(runs, threshold_hours=6.0, now=now)
        assert len(result) == 1
        assert result[0]["run_id"] == 5

    def test_returns_empty_list_when_no_runs_meet_threshold(self) -> None:
        now = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
        runs = [{"id": 3, "created_at": "2026-06-27T09:00:00Z", "html_url": "u3"}]  # age=1h
        result = filter_stuck_runs(runs, threshold_hours=6.0, now=now)
        assert result == []

    def test_returns_empty_list_on_empty_input(self) -> None:
        assert filter_stuck_runs([], threshold_hours=6.0) == []

    def test_skips_runs_with_blank_created_at(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        runs = [{"id": 4, "created_at": "", "html_url": "u4"}]
        assert filter_stuck_runs(runs, threshold_hours=0.0, now=now) == []

    def test_threshold_zero_returns_all_runs(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        runs = [
            {"id": 1, "created_at": "2026-06-27T06:00:00Z", "html_url": "u1"},
            {"id": 2, "created_at": "2026-06-27T19:30:00Z", "html_url": "u2"},
        ]
        result = filter_stuck_runs(runs, threshold_hours=0.0, now=now)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# diagnose_stuck_approvals
# ---------------------------------------------------------------------------


class TestDiagnoseStuckApprovals:
    def test_returns_parsed_runs_at_threshold_zero(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        runs = {"workflow_runs": [{"id": 9, "created_at": "2026-06-27T18:00:00Z", "html_url": "u9"}]}
        out = diagnose_stuck_approvals(gh_caller=lambda url: runs, threshold_hours=0.0, now=now)
        assert len(out) == 1
        assert out[0]["run_id"] == 9
        assert out[0]["url"] == "u9"

    def test_returns_empty_when_caller_yields_none(self) -> None:
        assert diagnose_stuck_approvals(gh_caller=lambda url: None) == []

    def test_swallows_caller_exception(self) -> None:
        def _boom(url: str) -> Any:
            raise RuntimeError("api down")

        assert diagnose_stuck_approvals(gh_caller=_boom) == []

    def test_does_not_filter_by_status_waiting(self) -> None:
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        captured: list[str] = []

        def _capture(url: str) -> Any:
            captured.append(url)
            return {"workflow_runs": []}

        diagnose_stuck_approvals(gh_caller=_capture, now=now)
        assert captured, "caller was never invoked"
        assert "status=waiting" not in captured[0], f"diagnose URL must not filter by status: {captured[0]}"


# ---------------------------------------------------------------------------
# main() diagnose mode
# ---------------------------------------------------------------------------


class TestMainDiagnoseMode:
    def test_diagnose_mode_does_not_call_escalate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONVERGENCE_HEALTH_DIAGNOSE", "1")
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.diagnose_stuck_approvals", return_value=[]),
            patch(
                "scripts.convergence_health.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.escalate") as esc,
        ):
            rc = main()
        assert rc == 0
        esc.assert_not_called()

    def test_diagnose_mode_calls_diagnose_stuck_approvals_not_find_stuck(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONVERGENCE_HEALTH_DIAGNOSE", "1")
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.diagnose_stuck_approvals", return_value=[]) as diag,
            patch("scripts.convergence_health.find_stuck_gated_approvals") as find_stuck,
            patch(
                "scripts.convergence_health.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.escalate"),
        ):
            main()
        diag.assert_called_once()
        find_stuck.assert_not_called()

    def test_normal_mode_calls_find_stuck_not_diagnose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONVERGENCE_HEALTH_DIAGNOSE", raising=False)
        with (
            patch("boto3.Session"),
            patch("scripts.convergence_health.read_convergence_record", return_value={"status": "green"}),
            patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]) as find_stuck,
            patch("scripts.convergence_health.diagnose_stuck_approvals") as diag,
            patch(
                "scripts.convergence_health.assess_health",
                return_value=HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none"),
            ),
            patch("scripts.convergence_health.escalate", return_value={"action": "none", "rec_id": None}),
        ):
            rc = main()
        assert rc == 0
        find_stuck.assert_called_once()
        diag.assert_not_called()


# ---------------------------------------------------------------------------
# DuckLake code-drift alarm (T2.38 / Decision 125/126)
# ---------------------------------------------------------------------------

_ALL_DUCKLAKE_FUNCTIONS = {
    _DUCKLAKE_WRITER_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_CATALOG_DR_FUNCTION,
}


class _FakeDeployRecordsS3:
    """Minimal S3 stub for read_deploy_record: same source_git_sha for every function's Key,
    unless a per-function override is supplied. A function absent from both sha_by_function and
    default_sha raises (simulating a missing/never-deployed record -> read_deploy_record's
    NoSuchKey path returns None)."""

    def __init__(self, default_sha: Any = None, sha_by_function: Optional[dict[str, str]] = None) -> None:
        self._default_sha = default_sha
        self._sha_by_function = sha_by_function or {}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        function = Key.rsplit("/", 1)[-1].removesuffix(".json")
        sha = self._sha_by_function.get(function, self._default_sha)
        if sha is None:
            raise RuntimeError("NoSuchKey")
        body = json.dumps({"code_sha256": "abc", "source_git_sha": sha}).encode()
        return {"Body": io.BytesIO(body)}


class TestFindOpenDucklakeDriftRec:
    def test_returns_first_matching_rec(self) -> None:
        recs = [
            {"id": "rec-100", "source": "ci_rca", "status": "open"},
            {"id": "rec-101", "source": "ducklake_code_drift", "status": "open"},
            {"id": "rec-102", "source": "ducklake_code_drift", "status": "closed"},
        ]
        result = find_open_ducklake_drift_rec(recs)
        assert result is not None
        assert result["id"] == "rec-101"

    def test_returns_none_when_no_match(self) -> None:
        recs = [{"id": "rec-100", "source": "tf_convergence_stale", "status": "open"}]
        assert find_open_ducklake_drift_rec(recs) is None

    def test_returns_none_on_empty_list(self) -> None:
        assert find_open_ducklake_drift_rec([]) is None


class TestDetectDucklakeCodeDrift:
    def _acts_caller(self, acts: list[str]):
        def _caller(action: str, fields: dict[str, Any]) -> Any:
            acts.append(action)
            return "rec-DRYRUN"

        return _caller

    def test_fresh_all_records_match_no_file(self) -> None:
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result == {"action": "none", "rec_id": None}
        assert acts == []

    def test_stale_all_records_mismatch_files_exactly_one(self) -> None:
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts.count("file") == 1

    def test_one_function_stale_still_files_exactly_one(self) -> None:
        """Only the writer is behind main -- ANY stale function triggers ONE rec, not per-function."""
        acts: list[str] = []
        s3 = _FakeDeployRecordsS3(
            default_sha="SHA_NEW",
            sha_by_function={_DUCKLAKE_WRITER_FUNCTION: "SHA_OLD"},
        )
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=s3,
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts == ["file"]

    def test_missing_record_counts_as_stale(self) -> None:
        """A function with NO deploy record at all (never governed-deployed) is stale, not fresh."""
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha=None),  # every get_object raises NoSuchKey
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_dedup_second_stale_tick_updates_not_files(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-321", "source": "ducklake_code_drift", "status": "open"}
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "update", "rec_id": "rec-321"}
        assert acts == ["update"]

    def test_fresh_with_open_rec_closes(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-654", "source": "ducklake_code_drift", "status": "open"}
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "close", "rec_id": "rec-654"}
        assert acts == ["close"]

    def test_reads_all_four_ducklake_functions(self) -> None:
        seen_functions: set[str] = set()

        class _RecordingS3:
            def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
                function = Key.rsplit("/", 1)[-1].removesuffix(".json")
                seen_functions.add(function)
                body = json.dumps({"code_sha256": "abc", "source_git_sha": "SHA_OLD"}).encode()
                return {"Body": io.BytesIO(body)}

        detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_RecordingS3(),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert seen_functions == _ALL_DUCKLAKE_FUNCTIONS

    def test_git_runner_receives_ducklake_source_pathspecs(self) -> None:
        captured_argv: list[list[str]] = []

        def _runner(argv: list[str]) -> str:
            captured_argv.append(argv)
            return "SHA_OLD"

        detect_ducklake_code_drift(
            git_runner=_runner,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert len(captured_argv) == 1
        argv = captured_argv[0]
        assert argv[:4] == ["git", "log", "-1", "--format=%H"]
        assert "src/common/ducklake_*.py" in argv
        assert "config/lambda/ducklake" in argv

    def test_rec_fields_shape_on_file(self) -> None:
        captured: dict[str, Any] = {}

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            if action == "file":
                captured.update(fields)
            return "rec-999"

        detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=_caller,
            open_recs=[],
        )
        assert captured["source"] == "ducklake_code_drift"
        assert captured["priority"] == "High"
        assert captured["status"] == "open"
        assert _DUCKLAKE_WRITER_FUNCTION in captured["context"]

    def test_open_recs_none_fetches_live_open_recs(self) -> None:
        with patch("scripts.convergence_health._fetch_open_recs", return_value=[]) as fetch:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                portal_caller=lambda a, f: "rec-x",
            )
        fetch.assert_called_once()
        assert result == {"action": "none", "rec_id": None}

    def test_s3_client_none_creates_boto3_session_client(self) -> None:
        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = _FakeDeployRecordsS3(default_sha="SHA_OLD")
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
                profile="agent_platform",
            )
        mock_session.assert_called_once_with(profile_name="agent_platform")
        assert result == {"action": "none", "rec_id": None}

    def test_no_portal_caller_uses_real_file_rec(self) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-live") as fr:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_NEW",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[],
            )
        fr.assert_called_once()
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_no_portal_caller_uses_real_update_rec_for_close(self) -> None:
        existing = {"id": "rec-200", "source": "ducklake_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[existing],
            )
        ur.assert_called_once()
        assert result == {"action": "close", "rec_id": "rec-200"}

    def test_default_git_runner_invokes_subprocess(self) -> None:
        completed = MagicMock(returncode=0, stdout="SHA_FROM_SUBPROCESS\n")
        with patch("scripts.convergence_health.subprocess.run", return_value=completed) as run:
            result = detect_ducklake_code_drift(
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_FROM_SUBPROCESS"),
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
            )
        run.assert_called_once()
        assert result == {"action": "none", "rec_id": None}


class TestMainDucklakeDrift:
    def test_happy_path_returns_zero(self) -> None:
        with patch(
            "scripts.convergence_health.detect_ducklake_code_drift",
            return_value={"action": "none", "rec_id": None},
        ) as detect:
            rc = main_ducklake_drift(profile="agent_platform")
        assert rc == 0
        detect.assert_called_once_with(profile="agent_platform")

    def test_exception_returns_one(self) -> None:
        with patch(
            "scripts.convergence_health.detect_ducklake_code_drift",
            side_effect=RuntimeError("boom"),
        ):
            rc = main_ducklake_drift()
        assert rc == 1
