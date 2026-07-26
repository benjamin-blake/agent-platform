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

    # DEP-11 (T2.47): pending_gated HealthVerdict field -- present / absent / red-coexistence.

    def test_pending_gated_absent_by_default(self) -> None:
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": ""}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.pending_gated is None

    def test_pending_gated_none_when_record_is_none(self) -> None:
        v = assess_health(None)
        assert v.pending_gated is None

    def test_pending_gated_present_when_marker_in_record(self) -> None:
        marker = {"routed_at": "2026-06-27T00:00:00Z", "run_url": "https://example.com/run/1", "commit_sha": "abc123"}
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "pending_gated": marker}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.pending_gated == marker

    def test_pending_gated_does_not_force_high_severity_on_its_own(self) -> None:
        """A routed-pending marker alone (no stuck_approvals) must not escalate severity --
        pending-gated is a distinct, non-failure state (Decision 55 anti-masking); only the
        SEPARATE stuck-approval sensor (T2.35) escalates on staleness."""
        marker = {"routed_at": "2026-06-27T00:00:00Z", "run_url": "https://example.com/run/1", "commit_sha": "abc123"}
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "pending_gated": marker}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.pending_gated is not None
        assert v.severity == "none"

    def test_pending_gated_coexists_with_red_status(self) -> None:
        """red-coexistence: pending_gated is orthogonal to status -- a record can carry both a
        red status (e.g. a later out-of-band drift) and a leftover pending_gated marker."""
        now = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        marker = {"routed_at": "2026-06-26T00:00:00Z", "run_url": "https://example.com/run/2", "commit_sha": "def456"}
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
            "commit_sha": "",
            "pending_gated": marker,
        }
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.status == "red"
        assert v.severity == "low"
        assert v.pending_gated == marker

    # Decision 154 / rec-2862: infra_error HealthVerdict field -- present / absent / severity floor.

    def test_infra_error_absent_by_default(self) -> None:
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": ""}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.infra_error is None

    def test_infra_error_none_when_record_is_none(self) -> None:
        v = assess_health(None)
        assert v.infra_error is None

    def test_infra_error_present_when_marker_in_record(self) -> None:
        marker = {
            "routed_at": "2026-06-27T00:00:00Z",
            "run_url": "https://example.com/run/1",
            "commit_sha": "abc123",
            "failed_step": "tf_init",
        }
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "infra_error": marker}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.infra_error == marker

    def test_infra_error_floors_severity_at_low_from_none(self) -> None:
        """The marker alone (green status, no other escalation signal) raises severity from
        'none' to 'low' -- the health surface must show the pre-apply-failure episode."""
        marker = {"routed_at": "2026-06-27T00:00:00Z", "run_url": "https://example.com/run/1", "commit_sha": "abc123"}
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "infra_error": marker}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.infra_error is not None
        assert v.severity == "low"

    def test_infra_error_never_downgrades_high_severity(self) -> None:
        """The floor only ever RAISES severity -- a marker coexisting with a stuck-approval
        escalation (already 'high') must never downgrade it to 'low'."""
        marker = {"routed_at": "2026-06-27T00:00:00Z", "run_url": "https://example.com/run/1", "commit_sha": "abc123"}
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "infra_error": marker}
        stuck = [{"run_id": 1, "age_hours": 8.0, "url": "https://example.com"}]
        v = assess_health(rec, stuck_approvals=stuck, git_runner=lambda cmd: "")
        assert v.infra_error is not None
        assert v.severity == "high"

    def test_infra_error_does_not_upgrade_red_low_to_something_else(self) -> None:
        """infra_error coexisting with an under-threshold red status must not change that red's
        own age-based severity -- the floor only adds a 'low' the record would not otherwise
        have; a red-under-threshold record already reads 'low' with or without the marker."""
        now = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        marker = {"routed_at": "2026-06-26T00:00:00Z", "run_url": "https://example.com/run/2", "commit_sha": "def456"}
        rec = {
            "status": "red",
            "timestamp": "2026-06-27T00:00:00Z",
            "drift_detected_at": "2026-06-27T00:00:00Z",
            "commit_sha": "",
            "infra_error": marker,
        }
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.status == "red"
        assert v.severity == "low"
        assert v.infra_error == marker

    def test_infra_error_excluded_from_red_age_escalation_high(self) -> None:
        """infra_error must not itself push an over-threshold red to a DIFFERENT severity than
        the red-age computation already would -- the marker is orthogonal to red-age escalation,
        never a substitute input to it."""
        now = datetime(2026, 6, 27, 20, 0, tzinfo=timezone.utc)
        marker = {"routed_at": "2026-06-24T00:00:00Z", "run_url": "https://example.com/run/3", "commit_sha": "ghi789"}
        rec = {
            "status": "red",
            "timestamp": "2026-06-24T22:09:58Z",
            "drift_detected_at": "2026-06-26T11:52:07Z",
            "commit_sha": "",
            "infra_error": marker,
        }
        v = assess_health(rec, git_runner=lambda cmd: "", now=now)
        assert v.status == "red"
        assert v.severity == "high"
        assert v.infra_error == marker

    def test_infra_error_malformed_marker_does_not_floor_severity(self) -> None:
        """A malformed marker (not a dict) reads as absent -- severity stays 'none', matching
        read_infra_error_marker's degrade-to-None contract."""
        rec = {"status": "green", "timestamp": "2026-06-27T00:00:00Z", "commit_sha": "", "infra_error": "not-a-dict"}
        v = assess_health(rec, git_runner=lambda cmd: "")
        assert v.infra_error is None
        assert v.severity == "none"
