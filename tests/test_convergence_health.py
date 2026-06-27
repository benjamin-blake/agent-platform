"""Unit tests for scripts.convergence_health.

All tests are free of live AWS, git, and network dependencies:
S3 client, git runner, GitHub API caller, and portal caller are injected.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import scripts.convergence_health as ch
from scripts.convergence_health import (
    HealthVerdict,
    assess_health,
    count_unapplied_tf_commits,
    derive_red_since,
    escalate,
    escalation_action,
    find_open_convergence_stale_rec,
    find_stuck_gated_approvals,
    main,
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
