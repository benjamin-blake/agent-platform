"""Unit tests for scripts.convergence_health.record (rec-2709 Wave 6 package-mirror).

Convergence-record read + red/record-age helpers + unapplied-terraform-commit counting. Free
of live AWS/git dependencies: the S3 client and git runner are injected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scripts.convergence_health import (
    count_unapplied_tf_commits,
    derive_red_since,
    read_convergence_record,
    red_age_hours,
)


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


class TestReadConvergenceRecordReraise:
    def test_non_nosuchkey_error_propagates(self) -> None:
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
        s3 = MagicMock()
        s3.get_object.side_effect = err
        with pytest.raises(ClientError):
            read_convergence_record(s3)


class TestCountUnappliedTfCommitsDefaultRunner:
    def test_default_runner_counts_commit_lines(self) -> None:
        completed = MagicMock(returncode=0, stdout="abc123\ndef456\n")
        with patch("scripts.convergence_health.record.subprocess.run", return_value=completed):
            assert count_unapplied_tf_commits("sha0") == 2

    def test_default_runner_returns_zero_on_failure(self) -> None:
        with patch("scripts.convergence_health.record.subprocess.run", side_effect=OSError("git missing")):
            assert count_unapplied_tf_commits("sha0") == 0
