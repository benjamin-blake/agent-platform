"""Unit tests for the dedup-effectiveness SLI in scripts.preflight.ci_rca_gauges (WS5).

All tests are free of live AWS, network, and DuckLake-reader dependencies: cache_rows /
open_recs are always injected, and the portal caller is injected for escalate tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from scripts.preflight.ci_rca_gauges import (
    DEDUP_EFFECTIVENESS_MIN_SAMPLE,
    DEDUP_EFFECTIVENESS_THRESHOLD,
    _compute_dedup_effectiveness,
    _escalate_dedup_effectiveness,
    escalate_dedup_effectiveness,
    find_open_dedup_effectiveness_rec,
    print_dedup_effectiveness_gauge,
)

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def _rec(
    rec_id: str,
    fingerprint: str | None,
    created_days_ago: float = 1,
    status: str = "open",
    source: str = "ci_rca",
    file: str = "scripts/foo.py",
) -> dict:
    ts = NOW - timedelta(days=created_days_ago)
    ctx = {"fingerprint": fingerprint} if fingerprint else {}
    return {
        "id": rec_id,
        "source": source,
        "status": status,
        "file": file,
        "created_timestamp": ts.isoformat(),
        "context_v2_json": json.dumps(ctx) if ctx else "",
    }


# ---------------------------------------------------------------------------
# _compute_dedup_effectiveness
# ---------------------------------------------------------------------------


class TestComputeDedupEffectiveness:
    def test_none_cache_returns_none(self) -> None:
        assert _compute_dedup_effectiveness(None, now=NOW) is None

    def test_zero_fingerprinted_is_full_effectiveness(self) -> None:
        gauge = _compute_dedup_effectiveness([], window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0
        assert gauge["duplicate_count"] == 0
        assert gauge["effectiveness"] == 1.0

    def test_no_duplicates_is_full_effectiveness(self) -> None:
        rows = [_rec("rec-1", "fp-a"), _rec("rec-2", "fp-b"), _rec("rec-3", "fp-c")]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 3
        assert gauge["duplicate_fingerprints"] == 0
        assert gauge["duplicate_count"] == 0
        assert gauge["effectiveness"] == 1.0

    def test_duplicate_fingerprint_group_lowers_effectiveness(self) -> None:
        """3 open recs share fp-a (should have deduped to 1) -- 2 are duplicates."""
        rows = [
            _rec("rec-1", "fp-a", created_days_ago=3),
            _rec("rec-2", "fp-a", created_days_ago=2),
            _rec("rec-3", "fp-a", created_days_ago=1),
            _rec("rec-4", "fp-b", created_days_ago=1),
        ]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 4
        assert gauge["distinct_fingerprints"] == 2
        assert gauge["duplicate_fingerprints"] == 1
        assert gauge["duplicate_count"] == 2
        assert gauge["effectiveness"] == pytest.approx(0.5)

    def test_ignores_closed_recs(self) -> None:
        rows = [_rec("rec-1", "fp-a", status="closed"), _rec("rec-2", "fp-a", status="closed")]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0

    def test_ignores_non_ci_rca_source(self) -> None:
        rows = [_rec("rec-1", "fp-a", source="manual"), _rec("rec-2", "fp-a", source="manual")]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0

    def test_ignores_rows_without_fingerprint(self) -> None:
        rows = [_rec("rec-1", None)]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0

    def test_ignores_rows_with_non_empty_context_but_no_fingerprint_key(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "ci_rca",
                "status": "open",
                "created_timestamp": NOW.isoformat(),
                "context_v2_json": json.dumps({"failure_category": "code_regression"}),
            }
        ]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0

    def test_window_filtering_excludes_old_rows(self) -> None:
        rows = [_rec("rec-1", "fp-a", created_days_ago=1), _rec("rec-2", "fp-b", created_days_ago=30)]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 1

    def test_malformed_context_v2_json_skipped(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "ci_rca",
                "status": "open",
                "created_timestamp": NOW.isoformat(),
                "context_v2_json": "{not valid json",
            }
        ]
        gauge = _compute_dedup_effectiveness(rows, window_days=14, now=NOW)
        assert gauge["total_fingerprinted"] == 0


# ---------------------------------------------------------------------------
# find_open_dedup_effectiveness_rec
# ---------------------------------------------------------------------------


class TestFindOpenDedupEffectivenessRec:
    def test_finds_matching_open_rec(self) -> None:
        rows = [
            _rec("rec-1", "fp-a", file="scripts/ci_rca/dedup.py"),
            _rec("rec-2", "fp-b", file="scripts/other.py"),
        ]
        found = find_open_dedup_effectiveness_rec(rows)
        assert found["id"] == "rec-1"

    def test_ignores_closed_marker_rec(self) -> None:
        rows = [_rec("rec-1", "fp-a", file="scripts/ci_rca/dedup.py", status="closed")]
        assert find_open_dedup_effectiveness_rec(rows) is None

    def test_ignores_non_marker_file(self) -> None:
        rows = [_rec("rec-1", "fp-a", file="scripts/ci_rca_evidence.py")]
        assert find_open_dedup_effectiveness_rec(rows) is None

    def test_no_match_returns_none(self) -> None:
        assert find_open_dedup_effectiveness_rec([]) is None


# ---------------------------------------------------------------------------
# escalate_dedup_effectiveness
# ---------------------------------------------------------------------------


def _gauge(total: int, duplicates: int, window_days: int = 14) -> dict:
    effectiveness = 1.0 - (duplicates / total) if total else 1.0
    return {
        "window_days": window_days,
        "total_fingerprinted": total,
        "distinct_fingerprints": total - duplicates,
        "duplicate_fingerprints": 1 if duplicates else 0,
        "duplicate_count": duplicates,
        "effectiveness": effectiveness,
    }


class TestEscalateDedupEffectiveness:
    def test_files_when_degraded_and_no_open_rec(self) -> None:
        gauge = _gauge(total=DEDUP_EFFECTIVENESS_MIN_SAMPLE, duplicates=2)
        assert gauge["effectiveness"] < DEDUP_EFFECTIVENESS_THRESHOLD
        caller = MagicMock(return_value="rec-900")

        result = escalate_dedup_effectiveness(gauge, open_recs=[], portal_caller=caller)

        assert result == {"action": "file", "rec_id": "rec-900"}
        caller.assert_called_once()
        action, fields = caller.call_args[0]
        assert action == "file"
        assert fields["source"] == "ci_rca"
        assert fields["file"] == "scripts/ci_rca/dedup.py"
        assert fields["status"] == "open"

    def test_updates_when_degraded_and_open_rec_exists(self) -> None:
        gauge = _gauge(total=DEDUP_EFFECTIVENESS_MIN_SAMPLE, duplicates=2)
        existing = _rec("rec-900", "fp-a", file="scripts/ci_rca/dedup.py")
        caller = MagicMock()

        result = escalate_dedup_effectiveness(gauge, open_recs=[existing], portal_caller=caller)

        assert result == {"action": "update", "rec_id": "rec-900"}
        caller.assert_called_once()
        action, fields = caller.call_args[0]
        assert action == "update"
        assert fields["id"] == "rec-900"

    def test_closes_when_recovered_and_open_rec_exists(self) -> None:
        gauge = _gauge(total=10, duplicates=0)
        existing = _rec("rec-900", "fp-a", file="scripts/ci_rca/dedup.py")
        caller = MagicMock()

        result = escalate_dedup_effectiveness(gauge, open_recs=[existing], portal_caller=caller)

        assert result == {"action": "close", "rec_id": "rec-900"}
        action, fields = caller.call_args[0]
        assert fields["status"] == "closed"

    def test_none_when_not_degraded_and_no_open_rec(self) -> None:
        gauge = _gauge(total=10, duplicates=0)
        caller = MagicMock()

        result = escalate_dedup_effectiveness(gauge, open_recs=[], portal_caller=caller)

        assert result == {"action": "none", "rec_id": None}
        caller.assert_not_called()

    def test_min_sample_gate_suppresses_escalation_on_tiny_sample(self) -> None:
        """Below min_sample, even 100% duplicate rate does not escalate."""
        gauge = _gauge(total=1, duplicates=1)
        caller = MagicMock()

        result = escalate_dedup_effectiveness(gauge, open_recs=[], portal_caller=caller)

        assert result == {"action": "none", "rec_id": None}
        caller.assert_not_called()

    def test_idempotent_repeated_calls_do_not_double_file(self) -> None:
        gauge = _gauge(total=DEDUP_EFFECTIVENESS_MIN_SAMPLE, duplicates=2)
        caller = MagicMock(return_value="rec-900")

        first = escalate_dedup_effectiveness(gauge, open_recs=[], portal_caller=caller)
        existing = _rec("rec-900", "fp-a", file="scripts/ci_rca/dedup.py")
        second = escalate_dedup_effectiveness(gauge, open_recs=[existing], portal_caller=caller)

        assert first["action"] == "file"
        assert second["action"] == "update"
        assert second["rec_id"] == "rec-900"

    def test_no_portal_caller_uses_real_file_rec(self) -> None:
        gauge = _gauge(total=DEDUP_EFFECTIVENESS_MIN_SAMPLE, duplicates=2)
        with pytest.MonkeyPatch.context() as mp:
            import scripts.ops_data_portal as p

            mock_file_rec = MagicMock(return_value="rec-901")
            mp.setattr(p, "file_rec", mock_file_rec)
            result = escalate_dedup_effectiveness(gauge, open_recs=[])
        assert result == {"action": "file", "rec_id": "rec-901"}
        mock_file_rec.assert_called_once()

    def test_no_portal_caller_uses_real_update_rec_on_update(self) -> None:
        gauge = _gauge(total=DEDUP_EFFECTIVENESS_MIN_SAMPLE, duplicates=2)
        existing = _rec("rec-900", "fp-a", file="scripts/ci_rca/dedup.py")
        with pytest.MonkeyPatch.context() as mp:
            import scripts.ops_data_portal as p

            mock_update_rec = MagicMock(return_value=True)
            mp.setattr(p, "update_rec", mock_update_rec)
            result = escalate_dedup_effectiveness(gauge, open_recs=[existing])
        assert result == {"action": "update", "rec_id": "rec-900"}
        mock_update_rec.assert_called_once()

    def test_no_portal_caller_uses_real_update_rec_on_close(self) -> None:
        gauge = _gauge(total=10, duplicates=0)
        existing = _rec("rec-900", "fp-a", file="scripts/ci_rca/dedup.py")
        with pytest.MonkeyPatch.context() as mp:
            import scripts.ops_data_portal as p

            mock_update_rec = MagicMock(return_value=True)
            mp.setattr(p, "update_rec", mock_update_rec)
            result = escalate_dedup_effectiveness(gauge, open_recs=[existing])
        assert result == {"action": "close", "rec_id": "rec-900"}
        mock_update_rec.assert_called_once()


# ---------------------------------------------------------------------------
# _escalate_dedup_effectiveness (preflight wiring)
# ---------------------------------------------------------------------------


class TestEscalateDedupEffectivenessWiring:
    def test_skips_when_creds_unavailable(self) -> None:
        assert _escalate_dedup_effectiveness("unavailable", [], {"total_fingerprinted": 0}) is None

    def test_skips_when_cache_rows_none(self) -> None:
        assert _escalate_dedup_effectiveness("ok", None, {"total_fingerprinted": 0}) is None

    def test_skips_when_gauge_none(self) -> None:
        assert _escalate_dedup_effectiveness("ok", [], None) is None

    def test_delegates_to_escalate_when_all_present(self) -> None:
        gauge = _gauge(total=10, duplicates=0)
        result = _escalate_dedup_effectiveness("ok", [], gauge)
        assert result == {"action": "none", "rec_id": None}

    def test_exception_in_escalate_is_caught_and_logged(self, capsys) -> None:
        bad_gauge = {"total_fingerprinted": "not-a-number"}
        result = _escalate_dedup_effectiveness("ok", [], bad_gauge)
        assert result is None
        assert "escalate_dedup_effectiveness() failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# print_dedup_effectiveness_gauge
# ---------------------------------------------------------------------------


class TestPrintDedupEffectivenessGauge:
    def test_none_gauge_prints_nothing(self, capsys) -> None:
        print_dedup_effectiveness_gauge(None)
        assert capsys.readouterr().out == ""

    def test_prints_effectiveness_percentage(self, capsys) -> None:
        gauge = _gauge(total=10, duplicates=1)
        print_dedup_effectiveness_gauge(gauge)
        out = capsys.readouterr().out
        assert "90%" in out
        assert "CI-RCA dedup effectiveness" in out
