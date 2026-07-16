"""ci_rca_signals-surface tests: CI-RCA liveness alert, convergence-RCA gap alert, fetch of
ci_rca recs (open / since-ts), derive-closed projection, dispute-open derivation and fetch,
dispute-recs printing, undetermined (abstention-review) recs derivation/fetch/printing
(rec-2709 Wave 4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestCiRcaLivenessAlert:
    """Tests for _check_ci_rca_liveness()."""

    def _make_gh_result(self, conclusion: str, created_at: str) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps([{"conclusion": conclusion, "createdAt": created_at, "url": "https://github.com/run/1"}])
        return result

    def test_alert_set_when_red_main_no_rec(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (
            patch("session_preflight.subprocess.run", return_value=self._make_gh_result("failure", old_ts)),
            patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs_since", return_value=[]),
        ):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is not None
        assert "run_url" in result
        assert result["elapsed_minutes"] > 30

    def test_alert_none_when_rec_exists_after_run(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (
            patch("session_preflight.subprocess.run", return_value=self._make_gh_result("failure", old_ts)),
            patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs_since", return_value=[{"id": "rec-1"}]),
        ):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is None

    def test_alert_none_when_main_is_green(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with patch("session_preflight.subprocess.run", return_value=self._make_gh_result("success", old_ts)):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is None

    def test_alert_none_when_creds_not_ok(self) -> None:
        result = _preflight._check_ci_rca_liveness("unavailable")
        assert result is None


class TestConvergenceRcaGapAlert:
    """Tests for _check_convergence_rca_gap() (PLAN-gated-apply-rca-trigger)."""

    def _red_health(self, red_age_hours: float = 1.0) -> dict:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(hours=red_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "status": "red",
            "red_age_hours": red_age_hours,
            "commit_sha": "0b81f6a184d1a74b075082801ec9de2bfc4157d8",  # pragma: allowlist secret
            "run_url": "https://github.com/org/repo/actions/runs/28379330706",
            "red_since": old_ts,
        }

    def test_convergence_rca_gap_alert_set_when_red_beyond_grace_no_matching_rec(self) -> None:
        with patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs_since", return_value=[]):
            result = _preflight._check_convergence_rca_gap(self._red_health())
        assert result is not None
        assert result["commit_sha"] == "0b81f6a184d1a74b075082801ec9de2bfc4157d8"  # pragma: allowlist secret
        assert result["red_age_hours"] == 1.0

    def test_convergence_rca_gap_alert_none_when_matching_open_rec_exists(self) -> None:
        with patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs_since", return_value=[{"id": "rec-1"}]):
            result = _preflight._check_convergence_rca_gap(self._red_health())
        assert result is None

    def test_convergence_rca_gap_alert_none_when_record_green(self) -> None:
        result = _preflight._check_convergence_rca_gap({"status": "green", "red_age_hours": 0.0})
        assert result is None

    def test_convergence_rca_gap_alert_none_when_red_within_grace(self) -> None:
        health = self._red_health(red_age_hours=0.1)  # 6 minutes, within the 30-minute grace
        with patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs_since", return_value=[]):
            result = _preflight._check_convergence_rca_gap(health)
        assert result is None

    def test_convergence_rca_gap_alert_none_when_health_is_none(self) -> None:
        assert _preflight._check_convergence_rca_gap(None) is None

    def test_convergence_rca_gap_alert_none_when_red_since_missing(self) -> None:
        health = {"status": "red", "red_age_hours": 1.0}
        result = _preflight._check_convergence_rca_gap(health)
        assert result is None


class TestFetchCiRcaRecs:
    """_fetch_ci_rca_recs / _fetch_ci_rca_recs_since transit the ci_rca_* named verbs."""

    def test_fetch_ci_rca_recs_uses_ci_rca_open_verb(self) -> None:
        rows = [{"id": "rec-900", "title": "CI broken", "priority": "critical"}]
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._fetch_ci_rca_recs()
        assert result == rows
        MockReader.return_value.named.assert_called_once_with("ci_rca_open")

    def test_fetch_ci_rca_recs_degrades_to_empty_with_warning(self, capsys: pytest.CaptureFixture) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            result = _preflight._fetch_ci_rca_recs()
        assert result == []
        assert "reader unreachable" in capsys.readouterr().err

    def test_fetch_ci_rca_recs_since_binds_since_ts(self) -> None:
        rows = [{"id": "rec-901"}]
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._fetch_ci_rca_recs_since("2026-06-10T00:00:00Z")
        assert result == rows
        MockReader.return_value.named.assert_called_once_with("ci_rca_since", since_ts="2026-06-10T00:00:00Z")

    def test_fetch_ci_rca_recs_since_returns_empty_on_failure(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            assert _preflight._fetch_ci_rca_recs_since("2026-06-10T00:00:00Z") == []


class TestDeriveCiRcaClosed:
    """Unit tests for _derive_ci_rca_closed() -- closed-sibling cluster projection."""

    def _make_row(
        self,
        rec_id: str,
        source: str = "ci_rca",
        status: str = "closed",
        file: str = "scripts/foo.py",
        title: str = "CI failure",
        last_updated: str = "2026-06-11T10:00:00Z",
    ) -> dict:
        return {
            "id": rec_id,
            "source": source,
            "status": status,
            "file": file,
            "title": title,
            "last_updated_timestamp": last_updated,
        }

    def test_only_closed_ci_rca_rows_returned(self) -> None:
        rows = [
            self._make_row("rec-901", status="closed"),
            self._make_row("rec-902", status="open"),
            self._make_row("rec-903", status="in_progress"),
            self._make_row("rec-904", source="manual", status="closed"),
        ]
        result = _preflight._derive_ci_rca_closed(rows)
        assert [r["id"] for r in result] == ["rec-901"]

    def test_projects_expected_fields(self) -> None:
        rows = [self._make_row("rec-910", file="scripts/bar.py", title="mypy error", last_updated="2026-06-15T12:00:00Z")]
        result = _preflight._derive_ci_rca_closed(rows)
        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "file", "title", "last_updated_timestamp"}
        assert result[0]["id"] == "rec-910"
        assert result[0]["file"] == "scripts/bar.py"
        assert result[0]["title"] == "mypy error"
        assert result[0]["last_updated_timestamp"] == "2026-06-15T12:00:00Z"

    def test_empty_rows_returns_empty(self) -> None:
        assert _preflight._derive_ci_rca_closed([]) == []

    def test_multiple_closed_ci_rca_all_returned(self) -> None:
        rows = [
            self._make_row("rec-920"),
            self._make_row("rec-921"),
            self._make_row("rec-922", status="superseded"),
        ]
        result = _preflight._derive_ci_rca_closed(rows)
        assert [r["id"] for r in result] == ["rec-920", "rec-921"]


class TestDeriveCiRcaDisputeOpen:
    """Unit tests for _derive_ci_rca_dispute_open() -- filter/sort/cap."""

    def _make_row(
        self,
        rec_id: str,
        source: str = "ci_rca_evidence_dispute",
        status: str = "open",
        created: str = "2026-06-29T10:00:00Z",
        title: str = "Dispute rec",
        priority: str = "low",
    ) -> dict:
        return {
            "id": rec_id,
            "source": source,
            "status": status,
            "created_timestamp": created,
            "title": title,
            "priority": priority,
        }

    def test_filters_by_source_and_open_status(self) -> None:
        """Only source=ci_rca_evidence_dispute + status in (open, in_progress) rows are returned."""
        rows = [
            self._make_row("rec-101", status="open"),
            self._make_row("rec-102", status="in_progress"),
            self._make_row("rec-103", status="closed"),
            self._make_row("rec-104", source="ci_rca", status="open"),
            self._make_row("rec-105", source="planning", status="open"),
        ]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert {r["id"] for r in result} == {"rec-101", "rec-102"}

    def test_newest_first_ordering(self) -> None:
        """Results are ordered newest-first by created_timestamp."""
        rows = [
            self._make_row("rec-201", created="2026-06-27T08:00:00Z"),
            self._make_row("rec-202", created="2026-06-29T12:00:00Z"),
            self._make_row("rec-203", created="2026-06-28T06:00:00Z"),
        ]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert [r["id"] for r in result] == ["rec-202", "rec-203", "rec-201"]

    def test_capped_at_five(self) -> None:
        """Result is capped at 5 rows."""
        rows = [self._make_row(f"rec-{300 + i}", created=f"2026-06-2{i}T00:00:00Z") for i in range(7)]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert len(result) == 5

    def test_projects_expected_fields(self) -> None:
        """Each returned dict has id, title, priority, created_timestamp."""
        rows = [self._make_row("rec-401", title="My dispute", priority="Low", created="2026-06-29T10:00:00Z")]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "title", "priority", "created_timestamp"}
        assert result[0]["id"] == "rec-401"
        assert result[0]["title"] == "My dispute"

    def test_empty_rows_returns_empty(self) -> None:
        assert _preflight._derive_ci_rca_dispute_open([]) == []


class TestFetchCiRcaDisputeRecs:
    """Unit tests for _fetch_ci_rca_dispute_recs() -- cache-row path."""

    def _make_dispute_row(self, rec_id: str, status: str = "open") -> dict:
        return {
            "id": rec_id,
            "source": "ci_rca_evidence_dispute",
            "status": status,
            "title": "Dispute rec",
            "priority": "low",
            "created_timestamp": "2026-06-29T10:00:00Z",
        }

    def test_cache_rows_supplied_returns_derived(self) -> None:
        """When cache_rows is a list, returns _derive_ci_rca_dispute_open result (no reader call)."""
        rows = [self._make_dispute_row("rec-501")]
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=rows)
        assert len(result) == 1
        assert result[0]["id"] == "rec-501"

    def test_cache_rows_none_returns_empty(self) -> None:
        """When cache_rows is None (warm-pull failed), returns []."""
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=None)
        assert result == []

    def test_sentinel_returns_empty(self) -> None:
        """When called with the sentinel (no cache_rows arg), returns [] -- no reader call."""
        result = _preflight._fetch_ci_rca_dispute_recs()
        assert result == []

    def test_filters_closed_rows_from_cache(self) -> None:
        """Closed dispute recs are excluded from the cache-path result."""
        rows = [
            self._make_dispute_row("rec-601", status="open"),
            self._make_dispute_row("rec-602", status="closed"),
        ]
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=rows)
        assert [r["id"] for r in result] == ["rec-601"]


class TestPrintCiRcaDisputeRecs:
    """Unit tests for print_ci_rca_dispute_recs() -- section rendering."""

    def test_empty_prints_none_line(self, capsys: pytest.CaptureFixture) -> None:
        """When recs is empty, prints the header and '(none)'."""
        _preflight.print_ci_rca_dispute_recs([])
        out = capsys.readouterr().out
        assert "CI-RCA Dispute Recs (open)" in out
        assert "(none)" in out

    def test_renders_rec_ids(self, capsys: pytest.CaptureFixture) -> None:
        """Each rec is rendered with its id, priority, timestamp, and title."""
        recs = [
            {
                "id": "rec-701",
                "title": "Bundle wrong on earliest_viable_gate",
                "priority": "low",
                "created_timestamp": "2026-06-29T10:00:00Z",
            },
        ]
        _preflight.print_ci_rca_dispute_recs(recs)
        out = capsys.readouterr().out
        assert "CI-RCA Dispute Recs (open)" in out
        assert "rec-701" in out
        assert "Bundle wrong on earliest_viable_gate" in out

    def test_header_printed_before_entries(self, capsys: pytest.CaptureFixture) -> None:
        """The section header appears before any rec lines."""
        recs = [{"id": "rec-801", "title": "Dispute", "priority": "low", "created_timestamp": "2026-06-29T10:00:00Z"}]
        _preflight.print_ci_rca_dispute_recs(recs)
        out = capsys.readouterr().out
        header_pos = out.index("CI-RCA Dispute Recs (open)")
        rec_pos = out.index("rec-801")
        assert header_pos < rec_pos


class TestFetchCiRcaUndeterminedRecs:
    """c7: session_preflight surfaces rca_confidence=undetermined recs for mandatory human review."""

    def _make_row(self, rec_id: str, rca_confidence: str | None = "undetermined") -> dict:
        import json as _json

        ctx: dict = {"schema_version": 2}
        if rca_confidence is not None:
            ctx["rca_confidence"] = rca_confidence
        return {
            "id": rec_id,
            "source": "ci_rca",
            "status": "open",
            "title": f"CI failure {rec_id}",
            "priority": "Critical",
            "created_timestamp": "2026-06-30T10:00:00Z",
            "context_v2_json": _json.dumps(ctx),
        }

    def test_returns_undetermined_recs(self):
        rows = [self._make_row("rec-1"), self._make_row("rec-2", rca_confidence="high")]
        result = _preflight._derive_ci_rca_undetermined_open(rows)
        assert len(result) == 1
        assert result[0]["id"] == "rec-1"

    def test_ignores_non_ci_rca_source(self):
        row = self._make_row("rec-1")
        row["source"] = "planning"
        result = _preflight._derive_ci_rca_undetermined_open([row])
        assert result == []

    def test_ignores_closed_recs(self):
        row = self._make_row("rec-1")
        row["status"] = "closed"
        result = _preflight._derive_ci_rca_undetermined_open([row])
        assert result == []

    def test_ignores_missing_context_v2_json(self):
        row = {"id": "rec-1", "source": "ci_rca", "status": "open", "context_v2_json": ""}
        result = _preflight._derive_ci_rca_undetermined_open([row])
        assert result == []

    def test_ignores_invalid_context_v2_json(self):
        row = {"id": "rec-1", "source": "ci_rca", "status": "open", "context_v2_json": "not-json{{{"}
        result = _preflight._derive_ci_rca_undetermined_open([row])
        assert result == []

    def test_capped_at_five(self):
        """CIRCA-10: the cap moved to print time -- derive returns the full untruncated list."""
        rows = [self._make_row(f"rec-{i}") for i in range(10)]
        result = _preflight._derive_ci_rca_undetermined_open(rows)
        assert len(result) == 10

    def test_fetch_passes_cache_rows(self):
        rows = [self._make_row("rec-99")]
        result = _preflight._fetch_ci_rca_undetermined_recs(cache_rows=rows)
        assert len(result) == 1
        assert result[0]["id"] == "rec-99"

    def test_fetch_returns_empty_for_none_cache(self):
        result = _preflight._fetch_ci_rca_undetermined_recs(cache_rows=None)
        assert result == []

    def test_print_ci_rca_undetermined_recs_empty(self, capsys):
        _preflight.print_ci_rca_undetermined_recs([])
        out = capsys.readouterr().out
        assert "none" in out

    def test_print_ci_rca_undetermined_recs_with_recs(self, capsys):
        recs = [{"id": "rec-1", "title": "CI broken", "priority": "Critical", "created_timestamp": "2026-06-30T10:00:00Z"}]
        _preflight.print_ci_rca_undetermined_recs(recs)
        out = capsys.readouterr().out
        assert "rec-1" in out
        assert "CI-RCA Abstention Review" in out

    def test_print_ci_rca_undetermined_recs_overflow(self, capsys):
        recs = [self._make_row(f"rec-{i}") for i in range(7)]
        _preflight.print_ci_rca_undetermined_recs(recs)
        out = capsys.readouterr().out
        assert "showing 5 of 7" in out

    def test_print_ci_rca_undetermined_recs_advisory_wording(self, capsys):
        recs = [self._make_row("rec-1")]
        _preflight.print_ci_rca_undetermined_recs(recs)
        out = capsys.readouterr().out
        assert "Mandatory" not in out
        assert "CI-RCA Abstention Review" in out
        assert "Decision 73 L5" in out
