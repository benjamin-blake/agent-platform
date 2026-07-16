"""Unit tests for scripts.convergence_health.assess (rec-2709 Wave 6 package-mirror).

HealthVerdict derivation and the escalation_action decision table.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import scripts.convergence_health as ch
from scripts.convergence_health import HealthVerdict, assess_health, escalation_action


class TestEscalationAction:
    def test_file_when_over_threshold_and_no_rec(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=False) == "file"

    def test_update_when_over_threshold_and_rec_exists(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=True) == "update"

    def test_close_when_under_threshold_and_rec_exists(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=True) == "close"

    def test_none_when_under_threshold_and_no_rec(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=False) == "none"


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

    def test_default_record_age_hours_is_zero_valued(self) -> None:
        v = HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0)
        assert v.record_age_hours == 0.0

    def test_record_age_hours_computed_regardless_of_colour(self) -> None:
        now = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": ""}
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.record_age_hours == pytest.approx(3.0, abs=0.01)

    def test_high_severity_for_green_record_with_stuck_approvals(self) -> None:
        """Acceptance criterion 1: severity 'high' for a GREEN record carrying stuck approvals
        (regression from the prior 'none' -- a routed gated-apply deliberately leaves the record
        green while it waits for a human reviewer)."""
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": ""}
        stuck = [{"run_id": 1, "age_hours": 8.0, "url": "https://example.com"}]
        v = assess_health(rec, stuck_approvals=stuck, git_runner=lambda cmd: "")
        assert v.status == "green"
        assert v.severity == "high"

    def test_high_severity_for_stale_green_backlog_over_threshold(self) -> None:
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "abc123"}
        git_output = "commit1 msg\ncommit2 msg"
        v = assess_health(rec, git_runner=lambda cmd: git_output, now=now)
        assert v.unapplied_backlog == 2
        assert v.record_age_hours >= ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS
        assert v.severity == "high"

    def test_none_severity_for_green_backlog_under_threshold(self) -> None:
        now = datetime(2026, 6, 27, 0, 5, tzinfo=timezone.utc)
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "abc123"}
        git_output = "commit1 msg"
        v = assess_health(rec, git_runner=lambda cmd: git_output, now=now)
        assert v.unapplied_backlog == 1
        assert v.record_age_hours < ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS
        assert v.severity == "none"
