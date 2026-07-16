"""ci_rca_gauges-surface tests: CI-RCA probe abstention gauge (compute/escalate/print/report),
CI-RCA telemetry section (recurrence distribution, warn-mode-reject rate, dispute/backlog/
override counts, report JSON), CI-RCA back-validation section (derive/print/report)
(rec-2709 Wave 4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestAbstentionGauge:
    """T1.13 c12(i): _compute_ci_rca_abstention / _escalate_ci_rca_probe_health / preflight report JSON."""

    def test_compute_returns_none_when_cache_unavailable(self) -> None:
        assert _preflight._compute_ci_rca_abstention(None) is None

    def test_compute_delegates_to_ci_rca_probe_health(self) -> None:
        with patch("scripts.ci_rca.probe_health.compute_abstention_rate", return_value=(2, 5, 0.4)) as mock_compute:
            gauge = _preflight._compute_ci_rca_abstention([{"id": "rec-1"}], window_days=14)
        mock_compute.assert_called_once_with([{"id": "rec-1"}], window_days=14)
        assert gauge == {
            "undetermined_count": 2,
            "total_count": 5,
            "rate": 0.4,
            "window_days": 14,
        }

    def test_escalate_skipped_when_creds_not_ok(self) -> None:
        with patch("scripts.ci_rca.probe_health.escalate") as mock_escalate:
            result = _preflight._escalate_ci_rca_probe_health(
                "unavailable", [{"id": "rec-1"}], {"undetermined_count": 1, "total_count": 1, "rate": 1.0, "window_days": 14}
            )
        assert result is None
        mock_escalate.assert_not_called()

    def test_escalate_skipped_when_cache_unavailable(self) -> None:
        with patch("scripts.ci_rca.probe_health.escalate") as mock_escalate:
            result = _preflight._escalate_ci_rca_probe_health(
                "ok", None, {"undetermined_count": 1, "total_count": 1, "rate": 1.0, "window_days": 14}
            )
        assert result is None
        mock_escalate.assert_not_called()

    def test_escalate_skipped_when_gauge_is_none(self) -> None:
        with patch("scripts.ci_rca.probe_health.escalate") as mock_escalate:
            result = _preflight._escalate_ci_rca_probe_health("ok", [{"id": "rec-1"}], None)
        assert result is None
        mock_escalate.assert_not_called()

    def test_escalate_invoked_on_warm_cache_path(self) -> None:
        cache_rows = [
            {"id": "rec-1", "status": "open"},
            {"id": "rec-2", "status": "closed"},
        ]
        gauge = {"undetermined_count": 3, "total_count": 6, "rate": 0.5, "window_days": 14}
        with patch(
            "scripts.ci_rca.probe_health.escalate", return_value={"action": "file", "rec_id": "rec-9"}
        ) as mock_escalate:
            result = _preflight._escalate_ci_rca_probe_health("ok", cache_rows, gauge)
        assert result == {"action": "file", "rec_id": "rec-9"}
        mock_escalate.assert_called_once()
        args, kwargs = mock_escalate.call_args
        assert args[0] == 3
        assert args[1] == 6
        assert args[2] == 0.5
        # open_recs filtered to status='open' only, from the injected cache -- no reader call.
        assert args[3] == [{"id": "rec-1", "status": "open"}]

    def test_escalate_failure_is_non_fatal(self) -> None:
        gauge = {"undetermined_count": 1, "total_count": 1, "rate": 1.0, "window_days": 14}
        with patch("scripts.ci_rca.probe_health.escalate", side_effect=RuntimeError("portal down")):
            result = _preflight._escalate_ci_rca_probe_health("ok", [], gauge)
        assert result is None

    def test_print_gauge_line_format(self, capsys: pytest.CaptureFixture) -> None:
        gauge = {"undetermined_count": 2, "total_count": 8, "rate": 0.25, "window_days": 14}
        _preflight.print_ci_rca_abstention_gauge(gauge)
        out = capsys.readouterr().out
        assert "CI-RCA probe abstention (last 14d): 2/8 undetermined (25%)" in out

    def test_print_gauge_noop_when_none(self, capsys: pytest.CaptureFixture) -> None:
        _preflight.print_ci_rca_abstention_gauge(None)
        out = capsys.readouterr().out
        assert out == ""

    def test_main_report_contains_abstention_gauge_fields(self, tmp_path: Path) -> None:
        """The gauge fields appear in the preflight report JSON, computed from the warm cache."""
        preflight_report = tmp_path / ".preflight-report.json"
        cache_rows = [
            {
                "id": "rec-1",
                "source": "ci_rca",
                "status": "open",
                "created_timestamp": datetime.now(timezone.utc).isoformat(),
                "context_v2_json": "",
            }
        ]
        warm_sync_stub = {
            "drained": {},
            "pulled": {},
            "rows": {"ops_recommendations": cache_rows, "ops_decisions": [], "ops_priority_queue": []},
            "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
        }
        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("main", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="ok"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.priority_queue.read_priority_queue", return_value=[]),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch("scripts.sync.ops.warm_sync", return_value=warm_sync_stub),
            patch(
                "scripts.preflight.context_docs.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 2",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.ci_rca.probe_health.escalate", return_value={"action": "none", "rec_id": None}) as mock_escalate,
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert "ci_rca_abstention_gauge" in data
        gauge = data["ci_rca_abstention_gauge"]
        assert gauge["total_count"] == 1
        assert gauge["undetermined_count"] == 0
        assert data["ci_rca_probe_health_escalation"] == {"action": "none", "rec_id": None}
        mock_escalate.assert_called_once()


class TestCiRcaTelemetrySection:
    """T1.13 c1/c3: _compute_ci_rca_telemetry / print_ci_rca_telemetry / preflight report JSON.

    Re-grounded (per docs/INTENT-ci-rca-methodology.md Section 7.1) from the originally-scoped
    Athena design to warm-cache-derived surfacing (Decision 88 zero-egress).
    """

    NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def _row(
        self,
        source: str = "ci_rca",
        created_days_ago: float = 1,
        recurrence_class: str | None = None,
        warn_mode_reject: bool = False,
        upload_status: str | None = None,
        override: bool = False,
    ) -> dict:
        import json as _json
        from datetime import timedelta as _timedelta

        created = (self.NOW - _timedelta(days=created_days_ago)).isoformat()
        ctx: dict = {}
        if recurrence_class is not None:
            ctx["recurrence_class"] = recurrence_class
        if warn_mode_reject:
            ctx["warn_mode_reject"] = {"reasons": ["schema_deficiency"], "mode_at_write": "warn"}
        if upload_status is not None:
            ctx["evidence_bundle_ref"] = {"upload_status": upload_status}
        if override:
            ctx["why_chain_terminus_override"] = {"reason": "test override"}
        return {
            "source": source,
            "created_timestamp": created,
            "context_v2_json": _json.dumps(ctx) if ctx else "",
        }

    def test_returns_none_when_cache_unavailable(self) -> None:
        assert _preflight._compute_ci_rca_telemetry(None) is None

    def test_recurrence_class_distribution(self) -> None:
        rows = [
            self._row(recurrence_class="novel"),
            self._row(recurrence_class="novel"),
            self._row(recurrence_class="instance_of_known_pattern"),
            self._row(recurrence_class="regression"),
        ]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["recurrence_class_distribution"] == {"novel": 2, "instance_of_known_pattern": 1, "regression": 1}
        assert telemetry["ci_rca_total"] == 4

    def test_warn_mode_reject_rate_computed_from_markers(self) -> None:
        rows = [
            self._row(warn_mode_reject=True),
            self._row(warn_mode_reject=False),
            self._row(warn_mode_reject=False),
            self._row(warn_mode_reject=False),
        ]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["warn_mode_reject_count"] == 1
        assert telemetry["ci_rca_total"] == 4
        assert telemetry["warn_mode_reject_rate"] == pytest.approx(0.25)

    def test_threshold_note_over_25_percent(self) -> None:
        rows = [self._row(warn_mode_reject=True), self._row(warn_mode_reject=True), self._row(warn_mode_reject=False)]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["warn_mode_reject_rate"] == pytest.approx(2 / 3)
        assert telemetry["warn_mode_reject_threshold_note"] == "enforcement may need tuning"

    def test_threshold_note_at_or_under_5_percent(self) -> None:
        rows = [self._row(warn_mode_reject=False) for _ in range(20)]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["warn_mode_reject_rate"] == 0.0
        assert telemetry["warn_mode_reject_threshold_note"] == "Phase-4 promotion gate met"

    def test_threshold_note_none_in_middle_band(self) -> None:
        rows = [self._row(warn_mode_reject=True)] + [self._row(warn_mode_reject=False) for _ in range(9)]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["warn_mode_reject_rate"] == pytest.approx(0.1)
        assert telemetry["warn_mode_reject_threshold_note"] is None

    def test_dispute_path_traffic_counted(self) -> None:
        rows = [self._row(source="ci_rca_evidence_dispute"), self._row(source="ci_rca_evidence_dispute"), self._row()]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["dispute_count"] == 2
        assert telemetry["ci_rca_total"] == 1

    def test_bundle_upload_backlog_counted(self) -> None:
        rows = [
            self._row(upload_status="ok"),
            self._row(upload_status="upload_failed"),
            self._row(upload_status=None),
        ]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["bundle_upload_backlog"] == 1

    def test_override_usage_counted(self) -> None:
        rows = [self._row(override=True), self._row(override=False)]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["why_chain_terminus_override_count"] == 1

    def test_window_filtering_excludes_old_rows(self) -> None:
        rows = [self._row(created_days_ago=1), self._row(created_days_ago=60)]
        telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry["ci_rca_total"] == 1

    def test_zero_total_guard(self) -> None:
        telemetry = _preflight._compute_ci_rca_telemetry([], window_days=7, now=self.NOW)
        assert telemetry["ci_rca_total"] == 0
        assert telemetry["warn_mode_reject_rate"] == 0.0

    def test_print_noop_body_when_none(self, capsys: pytest.CaptureFixture) -> None:
        _preflight.print_ci_rca_telemetry(None)
        out = capsys.readouterr().out
        assert "CI-RCA Telemetry" in out
        assert "unavailable" in out

    def test_print_renders_all_fields(self, capsys: pytest.CaptureFixture) -> None:
        telemetry = _preflight._compute_ci_rca_telemetry(
            [self._row(recurrence_class="novel", warn_mode_reject=True)], window_days=7, now=self.NOW
        )
        _preflight.print_ci_rca_telemetry(telemetry)
        out = capsys.readouterr().out
        assert "CI-RCA Telemetry (last 7d)" in out
        assert "novel=1" in out
        assert "Warn-mode reject rate: 1/1 (100%)" in out
        assert "enforcement may need tuning" in out
        assert "Dispute-path traffic: 0" in out
        assert "Bundle-upload backlog: 0" in out
        assert "why_chain_terminus_override usage: 0" in out

    def test_main_report_contains_ci_rca_telemetry_key(self) -> None:
        """ci_rca_telemetry lands in the report JSON, computed with zero new reader egress."""

        def _boom(*args, **kwargs):
            raise AssertionError("_compute_ci_rca_telemetry must not construct a DuckLake reader")

        rows = [self._row(recurrence_class="novel")]
        with patch("src.common.iceberg_reader.make_reader", side_effect=_boom):
            telemetry = _preflight._compute_ci_rca_telemetry(rows, window_days=7, now=self.NOW)
        assert telemetry is not None
        assert telemetry["ci_rca_total"] == 1


class TestCiRcaBackValidationSection:
    """T1.13 c12(iii): _derive_ci_rca_back_validation / print_ci_rca_back_validation / report JSON."""

    def test_returns_none_when_cache_unavailable(self) -> None:
        assert _preflight._derive_ci_rca_back_validation(None) is None

    def test_delegates_to_ci_rca_back_validation_module(self) -> None:
        flagged = [
            {
                "new_rec_id": "rec-2",
                "prior_rec_id": "rec-1",
                "file": "scripts/validate.py",
                "preventive_action_excerpt": "Fix it.",
            }
        ]
        with patch("scripts.ci_rca.back_validation.find_preventive_regressions", return_value=flagged) as mock_find:
            result = _preflight._derive_ci_rca_back_validation([{"id": "rec-1"}])
        mock_find.assert_called_once_with([{"id": "rec-1"}])
        assert result == flagged

    def test_empty_on_no_matches(self) -> None:
        with patch("scripts.ci_rca.back_validation.find_preventive_regressions", return_value=[]):
            result = _preflight._derive_ci_rca_back_validation([])
        assert result == []

    def test_print_none_body(self, capsys: pytest.CaptureFixture) -> None:
        _preflight.print_ci_rca_back_validation([])
        out = capsys.readouterr().out
        assert "CI-RCA Back-Validation" in out
        assert "none" in out

    def test_print_renders_flags(self, capsys: pytest.CaptureFixture) -> None:
        flagged = [
            {
                "new_rec_id": "rec-2",
                "prior_rec_id": "rec-1",
                "file": "scripts/validate.py",
                "preventive_action_excerpt": "Fix it.",
            }
        ]
        _preflight.print_ci_rca_back_validation(flagged)
        out = capsys.readouterr().out
        assert "rec-2" in out
        assert "rec-1" in out
        assert "scripts/validate.py" in out
        assert "CANDIDATE" in out

    def test_no_reader_call_in_derivation(self) -> None:
        """Decision-88 zero-egress guard: the back-validation derive never builds a reader."""

        def _boom(*args, **kwargs):
            raise AssertionError("_derive_ci_rca_back_validation must not construct a DuckLake reader")

        with patch("src.common.iceberg_reader.make_reader", side_effect=_boom):
            result = _preflight._derive_ci_rca_back_validation([])
        assert result == []
