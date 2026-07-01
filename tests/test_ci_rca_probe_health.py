"""Unit tests for scripts.ci_rca_probe_health.

All tests are free of live AWS, network, and DuckLake-reader dependencies:
open_recs is always injected (never fetched), and the portal caller is injected.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scripts.ci_rca_probe_health import (
    ABSTENTION_MIN_SAMPLE,
    ABSTENTION_RATE_THRESHOLD,
    compute_abstention_rate,
    escalate,
    escalation_action,
    find_open_probe_health_rec,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _rec(source: str, created_days_ago: float, rca_confidence: str | None = None, status: str = "open") -> dict:
    ts = NOW.replace(hour=0) - __import__("datetime").timedelta(days=created_days_ago)
    ctx = {}
    if rca_confidence is not None:
        ctx["rca_confidence"] = rca_confidence
    return {
        "id": f"rec-{hash((source, created_days_ago, rca_confidence)) % 10000}",
        "source": source,
        "status": status,
        "created_timestamp": ts.isoformat(),
        "context_v2_json": json.dumps(ctx) if ctx else "",
    }


# ---------------------------------------------------------------------------
# compute_abstention_rate
# ---------------------------------------------------------------------------


class TestComputeAbstentionRate:
    def test_zero_total_guard(self) -> None:
        undetermined, total, rate = compute_abstention_rate([], window_days=14, now=NOW)
        assert (undetermined, total, rate) == (0, 0, 0.0)

    def test_counts_undetermined_within_window(self) -> None:
        rows = [
            _rec("ci_rca", 1, rca_confidence="undetermined"),
            _rec("ci_rca", 2, rca_confidence="high"),
            _rec("ci_rca", 3, rca_confidence="undetermined"),
            _rec("ci_rca", 5, rca_confidence=None),
        ]
        undetermined, total, rate = compute_abstention_rate(rows, window_days=14, now=NOW)
        assert undetermined == 2
        assert total == 4
        assert rate == pytest.approx(0.5)

    def test_window_filtering_excludes_old_rows(self) -> None:
        rows = [
            _rec("ci_rca", 1, rca_confidence="undetermined"),
            _rec("ci_rca", 30, rca_confidence="undetermined"),  # outside 14d window
        ]
        undetermined, total, rate = compute_abstention_rate(rows, window_days=14, now=NOW)
        assert total == 1
        assert undetermined == 1

    def test_ignores_non_ci_rca_source(self) -> None:
        rows = [
            _rec("ci_rca_probe_health", 1, rca_confidence="undetermined"),
            _rec("manual", 1, rca_confidence="undetermined"),
        ]
        undetermined, total, rate = compute_abstention_rate(rows, window_days=14, now=NOW)
        assert (undetermined, total, rate) == (0, 0, 0.0)

    def test_malformed_context_v2_json_treated_as_not_undetermined(self) -> None:
        rows = [
            {
                "source": "ci_rca",
                "status": "open",
                "created_timestamp": NOW.isoformat(),
                "context_v2_json": "{not valid json",
            }
        ]
        undetermined, total, rate = compute_abstention_rate(rows, window_days=14, now=NOW)
        assert total == 1
        assert undetermined == 0


# ---------------------------------------------------------------------------
# escalation_action truth table (mirrors convergence_health.escalation_action)
# ---------------------------------------------------------------------------


class TestEscalationAction:
    def test_file_when_over_threshold_and_no_open_rec(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=False) == "file"

    def test_update_when_over_threshold_and_open_rec_exists(self) -> None:
        assert escalation_action(over_threshold=True, open_rec_exists=True) == "update"

    def test_close_when_under_threshold_and_open_rec_exists(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=True) == "close"

    def test_none_when_under_threshold_and_no_open_rec(self) -> None:
        assert escalation_action(over_threshold=False, open_rec_exists=False) == "none"


# ---------------------------------------------------------------------------
# find_open_probe_health_rec
# ---------------------------------------------------------------------------


class TestFindOpenProbeHealthRec:
    def test_finds_matching_open_rec(self) -> None:
        rows = [
            {"id": "rec-1", "source": "ci_rca", "status": "open"},
            {"id": "rec-2", "source": "ci_rca_probe_health", "status": "open"},
        ]
        found = find_open_probe_health_rec(rows)
        assert found is not None
        assert found["id"] == "rec-2"

    def test_ignores_closed_probe_health_rec(self) -> None:
        rows = [{"id": "rec-2", "source": "ci_rca_probe_health", "status": "closed"}]
        assert find_open_probe_health_rec(rows) is None

    def test_returns_none_when_absent(self) -> None:
        assert find_open_probe_health_rec([]) is None


# ---------------------------------------------------------------------------
# escalate() dispatch -- dedup, no reader construction
# ---------------------------------------------------------------------------


class TestEscalate:
    def test_files_when_over_threshold_and_no_open_rec(self) -> None:
        portal_caller = MagicMock(return_value="rec-9001")
        result = escalate(
            undetermined_count=5,
            total_count=10,
            rate=0.5,
            open_recs=[],
            portal_caller=portal_caller,
        )
        assert result == {"action": "file", "rec_id": "rec-9001"}
        portal_caller.assert_called_once()
        assert portal_caller.call_args[0][0] == "file"
        fields = portal_caller.call_args[0][1]
        assert fields["source"] == "ci_rca_probe_health"
        assert fields["status"] == "open"

    def test_dedup_updates_instead_of_filing_when_open_rec_exists(self) -> None:
        portal_caller = MagicMock()
        open_recs = [{"id": "rec-777", "source": "ci_rca_probe_health", "status": "open"}]
        result = escalate(
            undetermined_count=6,
            total_count=10,
            rate=0.6,
            open_recs=open_recs,
            portal_caller=portal_caller,
        )
        assert result == {"action": "update", "rec_id": "rec-777"}
        portal_caller.assert_called_once()
        assert portal_caller.call_args[0][0] == "update"

    def test_closes_when_under_threshold_and_open_rec_exists(self) -> None:
        portal_caller = MagicMock()
        open_recs = [{"id": "rec-777", "source": "ci_rca_probe_health", "status": "open"}]
        result = escalate(
            undetermined_count=1,
            total_count=20,
            rate=0.05,
            open_recs=open_recs,
            portal_caller=portal_caller,
        )
        assert result == {"action": "close", "rec_id": "rec-777"}
        portal_caller.assert_called_once()
        assert portal_caller.call_args[0][0] == "close"

    def test_none_when_under_threshold_and_no_open_rec(self) -> None:
        portal_caller = MagicMock()
        result = escalate(
            undetermined_count=0,
            total_count=20,
            rate=0.0,
            open_recs=[],
            portal_caller=portal_caller,
        )
        assert result == {"action": "none", "rec_id": None}
        portal_caller.assert_not_called()

    def test_min_sample_guard_suppresses_escalation_on_small_totals(self) -> None:
        """A 100% abstention rate on a single sample must not escalate (min_sample guard)."""
        portal_caller = MagicMock()
        result = escalate(
            undetermined_count=1,
            total_count=1,
            rate=1.0,
            open_recs=[],
            portal_caller=portal_caller,
            min_sample=ABSTENTION_MIN_SAMPLE,
        )
        assert result == {"action": "none", "rec_id": None}
        portal_caller.assert_not_called()

    def test_no_duplicate_filing_when_called_twice_with_same_open_rec_state(self) -> None:
        """Calling escalate() again with the now-filed rec injected dedupes to 'update', not a second 'file'."""
        portal_caller = MagicMock(return_value="rec-9002")
        first = escalate(undetermined_count=5, total_count=10, rate=0.5, open_recs=[], portal_caller=portal_caller)
        assert first["action"] == "file"

        second_open_recs = [{"id": first["rec_id"], "source": "ci_rca_probe_health", "status": "open"}]
        second = escalate(
            undetermined_count=6,
            total_count=10,
            rate=0.6,
            open_recs=second_open_recs,
            portal_caller=portal_caller,
        )
        assert second["action"] == "update"
        assert second["rec_id"] == first["rec_id"]
        assert portal_caller.call_count == 2

    def test_default_portal_caller_uses_file_rec(self) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-9003") as mock_file_rec:
            result = escalate(undetermined_count=5, total_count=10, rate=0.5, open_recs=[])
        assert result == {"action": "file", "rec_id": "rec-9003"}
        mock_file_rec.assert_called_once()

    def test_no_reader_constructed_in_read_path(self) -> None:
        """Critical divergence from convergence_health: escalate() never builds a DuckLake reader.

        Patches make_reader to raise; escalate() must still run correctly from the injected
        open_recs list without ever touching the reader (Decision 88 zero-egress claim).
        """

        def _boom(*args, **kwargs):
            raise AssertionError("escalate() must not construct a DuckLake reader")

        with patch("src.common.iceberg_reader.make_reader", side_effect=_boom):
            portal_caller = MagicMock(return_value="rec-9004")
            result = escalate(
                undetermined_count=5,
                total_count=10,
                rate=0.5,
                open_recs=[{"id": "rec-1", "source": "ci_rca", "status": "open"}],
                portal_caller=portal_caller,
            )
        assert result == {"action": "file", "rec_id": "rec-9004"}

    def test_close_records_rate_as_proof(self) -> None:
        portal_caller = MagicMock()
        open_recs = [{"id": "rec-777", "source": "ci_rca_probe_health", "status": "open"}]
        escalate(
            undetermined_count=1,
            total_count=20,
            rate=0.05,
            open_recs=open_recs,
            portal_caller=portal_caller,
        )
        updates = portal_caller.call_args[0][1]
        assert "5%" in updates["resolution"] or "0.05" in updates["resolution"] or "5.0%" in updates["resolution"]
        assert updates["status"] == "closed"

    def test_threshold_boundary_over_threshold_when_rate_equals_threshold(self) -> None:
        portal_caller = MagicMock(return_value="rec-9005")
        result = escalate(
            undetermined_count=3,
            total_count=10,
            rate=ABSTENTION_RATE_THRESHOLD,
            open_recs=[],
            portal_caller=portal_caller,
        )
        assert result["action"] == "file"
