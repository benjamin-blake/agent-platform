"""Tests for validate_outbox_staleness()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_outbox_staleness import validate_outbox_staleness


class TestValidateOutboxStaleness:
    """Tests for validate_outbox_staleness()."""

    def test_no_outbox_directory_passes(self, tmp_path: Path, capsys) -> None:
        """No outbox directory: passes with 'No outbox directory' message."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "No outbox directory" in captured.out
        assert failed == []

    def test_recent_files_passes(self, tmp_path: Path, capsys) -> None:
        """Outbox with files modified < 24h ago: passes with count displayed."""
        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations"
        outbox.mkdir(parents=True)
        (outbox / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "none stale" in captured.out
        assert failed == []

    def test_stale_files_prints_warning(self, tmp_path: Path, capsys) -> None:
        """Outbox with files modified > 24h ago: prints WARNING (not a hard failure)."""
        import os
        import time

        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations"
        outbox.mkdir(parents=True)
        stale_file = outbox / "stale.jsonl"
        stale_file.write_text("{}", encoding="utf-8")
        # Set mtime to 48h ago
        old_mtime = time.time() - 48 * 3600
        os.utime(str(stale_file), (old_mtime, old_mtime))

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        # Stale outbox is a warning only, not a hard failure
        assert failed == []
