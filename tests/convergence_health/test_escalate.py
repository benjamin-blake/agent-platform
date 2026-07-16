"""Unit tests for scripts.convergence_health.escalate (rec-2709 Wave 6 package-mirror).

Idempotent tf_convergence_stale file/update/close escalation. Free of live dependencies: the
portal caller and open-recs list are injected (plus a few live-path tests that patch the real
ops-portal / DuckLake-reader call sites directly).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import scripts.convergence_health as ch
from scripts.convergence_health import HealthVerdict, escalate, find_open_convergence_stale_rec


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


class TestEscalateGreenStuckApproval:
    def _make_verdict(self) -> HealthVerdict:
        return HealthVerdict(
            status="green",
            red_age_hours=0.0,
            unapplied_backlog=0,
            stuck_approvals=[{"run_id": 1, "age_hours": 8.0, "url": "https://example.com"}],
            severity="high",
        )

    def test_files_rec_for_green_stuck_approval(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-701"

        result = escalate(self._make_verdict(), portal_caller=_caller, open_recs=[])
        assert result == {"action": "file", "rec_id": "rec-701"}
        assert calls[0][0] == "file"
        assert calls[0][1]["title"] == ch._TITLE_STUCK_APPROVAL
        assert "waiting on" in calls[0][1]["context"]

    def test_second_tick_updates_not_files(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-702", "source": "tf_convergence_stale", "status": "open", "title": ch._TITLE_STUCK_APPROVAL}
        result = escalate(self._make_verdict(), portal_caller=_caller, open_recs=[existing])
        assert result == {"action": "update", "rec_id": "rec-702"}
        assert len(calls) == 1
        assert calls[0][0] == "update"

    def test_clearing_approvals_closes_with_stuck_approval_resolution(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {"id": "rec-703", "source": "tf_convergence_stale", "status": "open", "title": ch._TITLE_STUCK_APPROVAL}
        cleared_verdict = HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none")
        result = escalate(cleared_verdict, portal_caller=_caller, open_recs=[existing])
        assert result == {"action": "close", "rec_id": "rec-703"}
        assert calls[0][1]["resolution"] == ch._RESOLUTION_STUCK_APPROVAL


class TestEscalateGreenStaleBacklog:
    def _make_verdict(self, record_age_hours: float) -> HealthVerdict:
        return HealthVerdict(
            status="green",
            red_age_hours=0.0,
            unapplied_backlog=2,
            severity="high" if record_age_hours >= ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS else "none",
            record_age_hours=record_age_hours,
        )

    def test_files_rec_at_or_over_threshold(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-801"

        verdict = self._make_verdict(record_age_hours=ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS)
        result = escalate(verdict, portal_caller=_caller, open_recs=[])
        assert result == {"action": "file", "rec_id": "rec-801"}
        assert calls[0][1]["title"] == ch._TITLE_STALE_GREEN_BACKLOG
        assert "backlog" in calls[0][1]["context"]

    def test_no_file_under_threshold(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return "rec-802"

        verdict = self._make_verdict(record_age_hours=ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS - 0.5)
        result = escalate(verdict, portal_caller=_caller, open_recs=[])
        assert result == {"action": "none", "rec_id": None}
        assert not calls

    def test_second_tick_updates_not_files(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {
            "id": "rec-803",
            "source": "tf_convergence_stale",
            "status": "open",
            "title": ch._TITLE_STALE_GREEN_BACKLOG,
        }
        verdict = self._make_verdict(record_age_hours=ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS + 1.0)
        result = escalate(verdict, portal_caller=_caller, open_recs=[existing])
        assert result == {"action": "update", "rec_id": "rec-803"}
        assert len(calls) == 1

    def test_backlog_drained_closes_with_stale_backlog_resolution(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        existing = {
            "id": "rec-804",
            "source": "tf_convergence_stale",
            "status": "open",
            "title": ch._TITLE_STALE_GREEN_BACKLOG,
        }
        drained_verdict = HealthVerdict(
            status="green",
            red_age_hours=0.0,
            unapplied_backlog=0,
            severity="none",
            record_age_hours=ch.STALE_GREEN_BACKLOG_THRESHOLD_HOURS + 5.0,
        )
        result = escalate(drained_verdict, portal_caller=_caller, open_recs=[existing])
        assert result == {"action": "close", "rec_id": "rec-804"}
        assert calls[0][1]["resolution"] == ch._RESOLUTION_STALE_GREEN_BACKLOG


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


class TestEscalateLiveFetchAndPortal:
    """Cover the production paths: live open-recs fetch and the real ops-portal calls."""

    def _verdict(self, status: str = "red", red_age: float = 10.0) -> HealthVerdict:
        return HealthVerdict(status=status, red_age_hours=red_age, unapplied_backlog=0, severity="high")

    def test_escalate_fetches_open_recs_when_not_injected(self) -> None:
        with (
            patch("scripts.convergence_health.escalate._fetch_open_recs", return_value=[]) as fetch,
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
