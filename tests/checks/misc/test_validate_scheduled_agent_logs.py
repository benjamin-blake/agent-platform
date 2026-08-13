"""Tests for validate_scheduled_agent_logs()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks import registry
from scripts.checks.misc.validate_scheduled_agent_logs import validate_scheduled_agent_logs


class TestValidateScheduledAgentLogs:
    """Tests for validate_scheduled_agent_logs()."""

    def _make_run(self, changed_files: list[str]):
        """Return a mock for validate.run that reports the given changed files."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "\n".join(changed_files) + "\n" if changed_files else ""
            return result

        return mock_run

    def test_passes_with_valid_agent_log(self, tmp_path: Path) -> None:
        """Passes when all changed files are valid scheduled-agent JSONL logs."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text(
            '{"type": "priority-queue-entry", "timestamp": "2026-05-09T18:20:00Z", "rank": 1}\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_fails_on_canonical_state_write(self) -> None:
        """Fails when logs/.recommendations-log.jsonl appears in the diff."""
        changed = [
            "logs/agents/rec-curator/20260509T182000Z.jsonl",
            "logs/.recommendations-log.jsonl",
        ]
        with patch("scripts.checks._common.run", side_effect=self._make_run(changed)):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_fails_on_malformed_jsonl(self, tmp_path: Path) -> None:
        """Fails when a JSONL file contains a non-JSON line."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text("this is not json\n", encoding="utf-8")
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_fails_on_invalid_filename(self, tmp_path: Path) -> None:
        """Fails when JSONL filename does not match the ISO timestamp pattern."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "output.jsonl"
        log_file.write_text(
            '{"type": "cluster", "timestamp": "2026-05-09T18:20:00Z"}\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/output.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_skips_when_source_files_changed(self) -> None:
        """Skips validation when non-log files appear in the diff (feature branch)."""
        changed = [
            "scripts/validate.py",
            "logs/agents/rec-curator/20260509T182000Z.jsonl",
        ]
        with patch("scripts.checks._common.run", side_effect=self._make_run(changed)):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_skips_when_no_files_changed(self) -> None:
        """Skips validation when there are no changed files relative to main."""
        with patch("scripts.checks._common.run", side_effect=self._make_run([])):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []


class TestDeclaredAccounting:
    """Decision 170: all four exit paths declare an examined count or a skip."""

    def _make_run(self, changed_files: list[str]):
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "\n".join(changed_files) + "\n" if changed_files else ""
            return result

        return mock_run

    def test_empty_diff_declares_examined_zero(self) -> None:
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run([])),
            patch.object(registry, "examined") as mock_examined,
            patch.object(registry, "skipped") as mock_skipped,
        ):
            validate_scheduled_agent_logs([])
        mock_examined.assert_called_once_with(0, unit="changed_files")
        mock_skipped.assert_not_called()

    def test_not_a_scheduled_agent_branch_declares_a_skip(self) -> None:
        changed = ["scripts/validate.py", "logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch.object(registry, "examined") as mock_examined,
            patch.object(registry, "skipped") as mock_skipped,
        ):
            validate_scheduled_agent_logs([])
        mock_skipped.assert_called_once()
        mock_examined.assert_not_called()

    def test_engagement_path_declares_examined_count(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text(
            '{"type": "priority-queue-entry", "timestamp": "2026-05-09T18:20:00Z", "rank": 1}\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_scheduled_agent_logs([])
        mock_examined.assert_called_once_with(1, unit="changed_files")

    def test_non_agents_log_file_is_skipped(self, tmp_path: Path) -> None:
        """A logs/ file outside logs/agents/ (e.g. logs/debug/) is not filename/content-checked."""
        changed = ["logs/debug/some-debug-file.txt"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_missing_agent_log_file_is_skipped(self, tmp_path: Path) -> None:
        """A well-named logs/agents/ path that doesn't exist on disk (e.g. a deleted file in the
        diff) is skipped rather than crashing on a missing read."""
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_blank_line_in_jsonl_is_skipped(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text(
            '\n{"type": "priority-queue-entry", "timestamp": "2026-05-09T18:20:00Z"}\n\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_fails_on_missing_required_fields(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text('{"rank": 1}\n', encoding="utf-8")
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_canonical_state_violation_still_declares_examined(self) -> None:
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl", "logs/.recommendations-log.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch.object(registry, "examined") as mock_examined,
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        mock_examined.assert_called_once_with(2, unit="changed_files")
        assert "Scheduled agent log validation" in failed
