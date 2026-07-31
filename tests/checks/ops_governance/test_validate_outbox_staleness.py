"""Tests for validate_outbox_staleness()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_outbox_staleness import validate_outbox_staleness
from scripts.checks.registry import full_sequence, pre_sequence


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

    def test_clean_tree_passes(self, tmp_path: Path, capsys) -> None:
        """Outbox dir exists but holds no files: passes."""
        (tmp_path / "logs" / ".ops-outbox").mkdir(parents=True)

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "none stale" in captured.out
        assert failed == []

    def test_fresh_retired_file_fails(self, tmp_path: Path, capsys) -> None:
        """A fresh (< 24h) file in a retired-table dir hard-fails, regardless of age."""
        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations"
        outbox.mkdir(parents=True)
        (outbox / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "retired outbox dir" in captured.out
        assert failed

    def test_fresh_legacy_file_does_not_fail(self, tmp_path: Path, capsys) -> None:
        """A fresh (< 24h) file in a legacy staging dir passes."""
        outbox = tmp_path / "logs" / ".ops-outbox" / "telemetry"
        outbox.mkdir(parents=True)
        (outbox / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "none stale" in captured.out
        assert failed == []

    def test_stale_legacy_file_warns_without_failing(self, tmp_path: Path, capsys) -> None:
        """A legacy staging file modified > 24h ago: prints WARNING, not a hard failure."""
        import os
        import time

        outbox = tmp_path / "logs" / ".ops-outbox" / "telemetry"
        outbox.mkdir(parents=True)
        stale_file = outbox / "stale.jsonl"
        stale_file.write_text("{}", encoding="utf-8")
        old_mtime = time.time() - 48 * 3600
        os.utime(str(stale_file), (old_mtime, old_mtime))

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert failed == []

    def test_pending_suffix_dir_fails_like_retired(self, tmp_path: Path, capsys) -> None:
        """A *_pending dir is treated as retired -- any file in it hard-fails."""
        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations_pending"
        outbox.mkdir(parents=True)
        (outbox / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert failed


class TestRegistration:
    """validate_outbox_staleness must be registered in both presubmit tiers."""

    def test_registered_in_pre_sequence(self) -> None:
        names = {s.name for s in pre_sequence()}
        assert "validate_outbox_staleness" in names

    def test_registered_in_full_sequence(self) -> None:
        names = {s.name for s in full_sequence()}
        assert "validate_outbox_staleness" in names
