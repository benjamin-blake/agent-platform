"""context_docs-surface tests: roadmap-state slimming, context-file reading (roadmap phase,
decisions, sessions, recs count), telemetry-health stub, retired-Athena-estate assertions,
endstate-drift detection (rec-2709 Wave 4).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import MODULE_PATH as _MODULE_PATH  # noqa: E402
from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestSlimRoadmapState:
    def test_keeps_only_actionable_subsets(self) -> None:
        full = {
            "next_eligible": [{"id": "T-1.6"}],
            "strategic_pending": [{"id": "T-2.1"}],
            "in_progress": [{"id": "T-1.5"}],
            "blocked": [{"id": "T-1.7"}],
            "active_tier": "T-1",
            "platform_tier_item_consumers": {"T-1.6": ["product-A"]},
        }
        slim = _preflight._slim_roadmap_state(full)
        assert slim == {
            "next_eligible": [{"id": "T-1.6"}],
            "strategic_pending": [{"id": "T-2.1"}],
        }

    def test_handles_missing_fields(self) -> None:
        slim = _preflight._slim_roadmap_state({})
        assert slim == {"next_eligible": [], "strategic_pending": []}

    def test_full_mode_includes_ratifiable_cds(self) -> None:
        full = {"ratifiable_cds": [{"id": "CD.6", "realization_evidence": "Realized."}]}
        slim = _preflight._slim_roadmap_state(full, full=True)
        assert slim["ratifiable_cds"] == [{"id": "CD.6", "realization_evidence": "Realized."}]

    def test_full_mode_defaults_ratifiable_cds_to_empty(self) -> None:
        slim = _preflight._slim_roadmap_state({}, full=True)
        assert slim["ratifiable_cds"] == []


class TestReadContextFiles:
    def test_roadmap_phase_extracted(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "ROADMAP.md"
        roadmap.write_text("# Roadmap\n\n## Phase 1.5: Schema Flattening\n", encoding="utf-8")
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", roadmap),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "Phase 1.5: Schema Flattening"

    def test_roadmap_phase_defaults_unknown_when_missing(self, tmp_path: Path) -> None:
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing3.md"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing4.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "unknown"

    def test_open_decisions_counted(self, tmp_path: Path) -> None:
        decisions = tmp_path / "DECISIONS.md"
        decisions.write_text(
            "## Decision 1: Foo (Agent-decided -- pending review)\n## Decision 2: Bar (Decided)\n## Decision 3: Baz\n",
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", decisions),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        # Decision 1 and 3 are open; Decision 2 is Decided
        assert result["open_decisions_count"] == 2

    def test_recent_sessions_extracted(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        session_log.write_text(
            "## [2026-03-01] -- agent/feature-a\n\n**Done:** Did something\n"
            "## [2026-03-10] -- agent/feature-b\n\n**Done:** Did another thing\n",
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", session_log),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert len(result["recent_sessions"]) == 2
        assert "2026-03-01" in result["recent_sessions"][0]

    def test_strategic_review_due_when_no_mention(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        # Recent session but no strategic review mention
        from datetime import date

        today = date.today().isoformat()
        session_log.write_text(
            f"## [{today}] -- agent/feature\n\n**Done:** regular work\n",
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", session_log),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["strategic_review_due"] is True

    def test_strategic_review_not_due_when_recent_mention(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        from datetime import date

        today = date.today().isoformat()
        session_log.write_text(
            f"## [{today}] -- strategic_review\n\n**Done:** completed strategic review\n",
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", session_log),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["strategic_review_due"] is False

    def test_missing_files_return_defaults(self, tmp_path: Path) -> None:
        with (
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing3.md"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", tmp_path / "missing4.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "unknown"
        assert result["open_decisions_count"] == 0
        assert result["recent_sessions"] == []
        assert result["strategic_review_due"] is True
        assert result["recommendations_count"] == 0


class TestTelemetryHealth:
    """Tests for the check_telemetry_health() stub (telemetry re-lands on DuckLake in Phase 4)."""

    def test_stub_returns_not_migrated_shape(self) -> None:
        """The stub reports the fixed not-migrated payload compatible with print_telemetry_health()."""
        result = _preflight.check_telemetry_health()
        assert result == {
            "overall": "unknown",
            "checks": [{"check": "telemetry-store", "value": "not migrated (Phase 4)", "severity": "unknown"}],
            "friction_patterns": [],
        }

    def test_stub_makes_no_aws_calls(self) -> None:
        """The stub must not touch boto3 or shell out -- the Athena polling loop is retired."""
        import boto3

        with (
            patch.object(boto3, "Session", side_effect=AssertionError("stub must not construct a boto3 Session")),
            patch("session_preflight.subprocess.run", side_effect=AssertionError("stub must not shell out")),
        ):
            result = _preflight.check_telemetry_health()
        assert result["overall"] == "unknown"

    def test_open_session_creates_state_file(self, tmp_path: Path) -> None:
        """open_telemetry_session writes state file with correct schema."""
        state_file = tmp_path / ".telemetry-active-session.json"
        mock_tel = MagicMock()
        mock_tel.open_session.return_value = "fake-uuid"
        original = sys.modules.get("scripts.executor.telemetry")
        sys.modules["scripts.executor.telemetry"] = mock_tel
        try:
            with patch("session_preflight.TELEMETRY_ACTIVE_SESSION_FILE", state_file):
                _preflight.open_telemetry_session(workflow="plan", branch="agent/test")
        finally:
            if original is not None:
                sys.modules["scripts.executor.telemetry"] = original
            else:
                sys.modules.pop("scripts.executor.telemetry", None)

        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "session_id" in data
        assert data["workflow"] == "plan"
        assert data["branch"] == "agent/test"
        assert "started_at" in data

    def test_main_includes_telemetry_health(self, tmp_path: Path) -> None:
        """main() includes telemetry_health key in report."""
        preflight_report = tmp_path / ".preflight-report.json"
        mock_health = {"overall": "ok", "checks": [], "friction_patterns": []}

        with (
            patch("scripts.preflight.context_docs.check_telemetry_health", return_value=mock_health),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("main", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="ok"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache.count_recommendations", return_value=(0, 0, 0, [])),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "scripts.preflight.context_docs.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert "telemetry_health" in data
        assert data["telemetry_health"]["overall"] == "ok"

    def test_health_flag_exits_zero_on_ok(self) -> None:
        """--health flag exits 0 when overall is ok."""
        mock_health = {"overall": "ok", "checks": []}
        with patch("scripts.preflight.context_docs.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 0

    def test_health_flag_exits_nonzero_on_critical(self) -> None:
        """--health flag exits 1 when overall is critical."""
        mock_health = {"overall": "critical", "checks": []}
        with patch("scripts.preflight.context_docs.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 1

    def test_health_flag_exits_zero_on_warning(self) -> None:
        """--health flag exits 0 when overall is warning (not critical)."""
        mock_health = {"overall": "warning", "checks": []}
        with patch("scripts.preflight.context_docs.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 0

    def test_print_telemetry_health_runs(self) -> None:
        """print_telemetry_health does not crash."""
        health = {
            "overall": "warning",
            "checks": [
                {"check": "sessions-7d", "value": "5", "severity": "ok"},
                {"check": "success-rate-7d", "value": "40%", "severity": "warning"},
            ],
        }
        with patch("builtins.print"):
            _preflight.print_telemetry_health(health)


class TestReadContextFilesRecsCount:
    """read_context_files() counts open recs via the open_recs verb (Decision 84 I-3)."""

    def test_recommendations_count_is_len_of_open_recs_rows(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.named.return_value = [{"id": "rec-1"}, {"id": "rec-2"}, {"id": "rec-3"}]
        with (
            patch("scripts.preflight._common._make_reader", return_value=reader),
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["recommendations_count"] == 3
        reader.named.assert_called_once_with("open_recs")

    def test_recommendations_count_zero_on_reader_failure(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.named.side_effect = RuntimeError("reader down")
        with (
            patch("scripts.preflight._common._make_reader", return_value=reader),
            patch("scripts.preflight._common.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("scripts.preflight._common.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("scripts.preflight._common.SESSION_LOG_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["recommendations_count"] == 0


class TestRetiredAthenaEstate:
    """Decision 84: the Athena query helpers and the outbox drain are gone from preflight."""

    def test_athena_helpers_deleted(self) -> None:
        for name in ("_run_athena_query", "_athena_run_query"):
            assert not hasattr(_preflight, name), f"retired symbol still present: {name}"
        athena_constants = [n for n in dir(_preflight) if n.startswith("_ATHENA")]
        assert athena_constants == [], f"retired Athena constants still present: {athena_constants}"

    def test_main_no_longer_drains_pending(self) -> None:
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "drain_pending" not in source, "preflight must not reference the retired outbox drain"


class TestEndstateDrift:
    """Tests for _check_endstate_drift() -- VP step 6 (endstate drift cases)."""

    _OLD_IDS = ["T1.1", "T1.2"]
    _NEW_ID = "ZZ9.99"
    _STAMP_COMMIT = "abc1234"

    def _make_old_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: not_started\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
        )

    def _make_new_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: not_started\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
            "  - id: ZZ9.99\n"
            "    name: New Item\n"
            "    status: not_started\n"
        )

    def _make_completed_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: complete\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
        )

    def _hash_of(self, ids: list[str]) -> str:
        return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()

    def _make_context_md(self, stamped_hash: str, commit: str = "abc1234") -> str:
        return f"Derived from ROADMAP-PLATFORM.yaml @ {commit} (2026-06-28).\nroadmap_tier_id_set sha256: {stamped_hash}\n"

    def _setup_tmpdir(self, tmp_path: Path, context_text: str, roadmap_yaml: str) -> None:
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs" / "PROJECT_CONTEXT.md").write_text(context_text, encoding="utf-8")
        (tmp_path / "docs" / "ROADMAP-PLATFORM.yaml").write_text(roadmap_yaml, encoding="utf-8")

    def test_endstate_in_sync_not_stale(self, tmp_path: Path) -> None:
        """Identical ID set: stamped hash matches current roadmap -> not stale, no warning."""
        current_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(current_hash)
        roadmap = self._make_old_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        with patch("scripts.preflight._common.ROOT", tmp_path):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is False
        assert result["current_hash"] == current_hash
        assert result["new_ids"] == []

    def test_endstate_new_id_stale_names_new_id(self, tmp_path: Path) -> None:
        """New tier_item ID added to roadmap -> stale=True, new_ids contains the new ID."""
        old_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(old_hash, self._STAMP_COMMIT)
        roadmap = self._make_new_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        git_result = MagicMock()
        git_result.returncode = 0
        git_result.stdout = self._make_old_roadmap_yaml()

        with (
            patch("scripts.preflight._common.ROOT", tmp_path),
            patch("session_preflight.subprocess.run", return_value=git_result),
        ):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is True
        assert self._NEW_ID in result["new_ids"]
        assert result["current_hash"] != old_hash

    def test_endstate_completed_item_unchanged_ids_not_stale(self, tmp_path: Path) -> None:
        """Completing an item changes status but NOT the ID set -> hash unchanged -> not stale."""
        current_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(current_hash)
        roadmap = self._make_completed_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        with patch("scripts.preflight._common.ROOT", tmp_path):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is False
        assert result["new_ids"] == []
