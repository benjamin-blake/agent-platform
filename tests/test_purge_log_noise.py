"""Unit tests for scripts/purge_log_noise.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import scripts.purge_log_noise as mod
from scripts.purge_log_noise import (
    _archive,
    _is_test_leakage,
    _read_jsonl,
    _write_jsonl,
    main,
    purge_retro,
    purge_telemetry,
)


def _make_jsonl(path: Path, entries: list[dict]) -> None:
    """Write entries as JSONL to path."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _load_jsonl(path: Path) -> list[dict]:
    """Load JSONL from path."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestIsTestLeakage:
    """Tests for _is_test_leakage predicate."""

    def test_matches_agent_test_manual_zero_files(self) -> None:
        entry = {
            "branch": "agent/test",
            "workflow": "manual",
            "files_changed": 0,
        }
        assert _is_test_leakage(entry) is True

    def test_rejects_different_branch(self) -> None:
        entry = {
            "branch": "agent/rec-100",
            "workflow": "manual",
            "files_changed": 0,
        }
        assert _is_test_leakage(entry) is False

    def test_rejects_nonzero_files(self) -> None:
        entry = {
            "branch": "agent/test",
            "workflow": "manual",
            "files_changed": 3,
        }
        assert _is_test_leakage(entry) is False

    def test_rejects_different_workflow(self) -> None:
        entry = {
            "branch": "agent/test",
            "workflow": "executor",
            "files_changed": 0,
        }
        assert _is_test_leakage(entry) is False


class TestPurgeTelemetry:
    """Tests for purge_telemetry function."""

    def test_removes_test_leakage(self) -> None:
        entries = [
            {
                "branch": "agent/test",
                "workflow": "manual",
                "files_changed": 0,
                "rec_id": None,
                "outcome": "completed",
                "end_time": "2026-04-01T10:00:00",
            },
            {
                "branch": "main",
                "workflow": "manual",
                "files_changed": 5,
                "rec_id": "rec-100",
                "outcome": "completed",
                "end_time": "2026-04-01T11:00:00",
            },
        ]
        cleaned, leakage, dups = purge_telemetry(entries)
        assert leakage == 1
        assert dups == 0
        assert len(cleaned) == 1
        assert cleaned[0]["branch"] == "main"

    def test_deduplicates_same_minute(self) -> None:
        base = {
            "branch": "main",
            "workflow": "executor",
            "files_changed": 2,
            "rec_id": "rec-200",
            "outcome": "success",
        }
        entries = [
            {**base, "end_time": "2026-04-01T10:05:01"},
            {**base, "end_time": "2026-04-01T10:05:59"},
        ]
        cleaned, leakage, dups = purge_telemetry(entries)
        assert leakage == 0
        assert dups == 1
        assert len(cleaned) == 1
        assert cleaned[0]["end_time"] == "2026-04-01T10:05:01"

    def test_keeps_different_minutes(self) -> None:
        base = {
            "branch": "main",
            "workflow": "executor",
            "files_changed": 2,
            "rec_id": "rec-200",
            "outcome": "success",
        }
        entries = [
            {**base, "end_time": "2026-04-01T10:05:01"},
            {**base, "end_time": "2026-04-01T10:06:01"},
        ]
        cleaned, leakage, dups = purge_telemetry(entries)
        assert dups == 0
        assert len(cleaned) == 2

    def test_preserves_non_matching_entries(self) -> None:
        entries = [
            {
                "branch": "main",
                "workflow": "executor",
                "files_changed": 3,
                "rec_id": "rec-300",
                "outcome": "success",
                "end_time": "2026-04-01T10:00:00",
            },
            {
                "branch": "agent/rec-301",
                "workflow": "executor",
                "files_changed": 1,
                "rec_id": "rec-301",
                "outcome": "failure",
                "end_time": "2026-04-01T11:00:00",
            },
        ]
        cleaned, leakage, dups = purge_telemetry(entries)
        assert leakage == 0
        assert dups == 0
        assert len(cleaned) == 2

    def test_empty_input(self) -> None:
        cleaned, leakage, dups = purge_telemetry([])
        assert cleaned == []
        assert leakage == 0
        assert dups == 0


class TestPurgeRetro:
    """Tests for purge_retro function."""

    def test_deduplicates_by_session_friction(self) -> None:
        entries = [
            {"timestamp": "2026-03-01T00:00:00Z", "session": "sess-A", "friction": "problem 1"},
            {"timestamp": "2026-03-02T00:00:00Z", "session": "sess-A", "friction": "problem 1"},
        ]
        cleaned, dups = purge_retro(entries)
        assert dups == 1
        assert len(cleaned) == 1
        assert cleaned[0]["timestamp"] == "2026-03-01T00:00:00Z"

    def test_keeps_different_friction(self) -> None:
        entries = [
            {"timestamp": "2026-03-01T00:00:00Z", "session": "sess-A", "friction": "problem 1"},
            {"timestamp": "2026-03-01T00:00:00Z", "session": "sess-A", "friction": "problem 2"},
        ]
        cleaned, dups = purge_retro(entries)
        assert dups == 0
        assert len(cleaned) == 2

    def test_empty_input(self) -> None:
        cleaned, dups = purge_retro([])
        assert cleaned == []
        assert dups == 0


class TestReadWriteJsonl:
    """Tests for _read_jsonl and _write_jsonl."""

    def test_round_trip(self, tmp_path: Path) -> None:
        entries = [{"a": 1}, {"b": 2}]
        path = tmp_path / "test.jsonl"
        _write_jsonl(path, entries)
        result = _read_jsonl(path)
        assert result == entries

    def test_read_missing_file(self, tmp_path: Path) -> None:
        result = _read_jsonl(tmp_path / "missing.jsonl")
        assert result == []


class TestArchive:
    """Tests for _archive function."""

    def test_creates_archive(self, tmp_path: Path) -> None:
        src = tmp_path / "logs" / ".test.jsonl"
        src.parent.mkdir(parents=True)
        src.write_text('{"x": 1}\n', encoding="utf-8")
        archive_dir = tmp_path / "logs" / "archive"
        with patch.object(mod, "ARCHIVE_DIR", archive_dir):
            result = _archive(src)
        assert result is True
        dest = archive_dir / ".test-pre-purge.jsonl"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == '{"x": 1}\n'

    def test_skips_if_archive_exists(self, tmp_path: Path) -> None:
        src = tmp_path / ".test.jsonl"
        src.write_text('{"x": 1}\n', encoding="utf-8")
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        dest = archive_dir / ".test-pre-purge.jsonl"
        dest.write_text('{"old": true}\n', encoding="utf-8")
        with patch.object(mod, "ARCHIVE_DIR", archive_dir):
            result = _archive(src)
        assert result is False
        assert dest.read_text(encoding="utf-8") == '{"old": true}\n'

    def test_returns_false_for_missing_source(
        self,
        tmp_path: Path,
    ) -> None:
        result = _archive(tmp_path / "nonexistent.jsonl")
        assert result is False


class TestDryRun:
    """Tests for --dry-run mode via main()."""

    def test_dry_run_prints_counts_without_modifying(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        tel_path = tmp_path / ".session-telemetry.jsonl"
        retro_path = tmp_path / ".retro-lite-log.jsonl"
        _make_jsonl(
            tel_path,
            [
                {
                    "branch": "agent/test",
                    "workflow": "manual",
                    "files_changed": 0,
                    "rec_id": None,
                    "outcome": "completed",
                    "end_time": "2026-04-01T10:00:00",
                },
                {
                    "branch": "main",
                    "workflow": "executor",
                    "files_changed": 2,
                    "rec_id": "rec-1",
                    "outcome": "success",
                    "end_time": "2026-04-01T11:00:00",
                },
            ],
        )
        _make_jsonl(
            retro_path,
            [
                {"timestamp": "2026-01-01T00:00:00Z", "session": "s1", "friction": "f1"},
            ],
        )
        original_tel = tel_path.read_text(encoding="utf-8")
        original_retro = retro_path.read_text(encoding="utf-8")

        with (
            patch.object(mod, "TELEMETRY_FILE", tel_path),
            patch.object(mod, "RETRO_FILE", retro_path),
            patch(
                "argparse.ArgumentParser.parse_args",
                return_value=type(
                    "Args",
                    (),
                    {"dry_run": True},
                )(),
            ),
        ):
            main()

        out = capsys.readouterr().out
        assert "would remove" in out
        assert tel_path.read_text(encoding="utf-8") == original_tel
        assert retro_path.read_text(encoding="utf-8") == original_retro


class TestIdempotency:
    """Running purge twice yields the same result."""

    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        entries = [
            {
                "branch": "agent/test",
                "workflow": "manual",
                "files_changed": 0,
                "rec_id": None,
                "outcome": "completed",
                "end_time": "2026-04-01T10:00:00",
            },
            {
                "branch": "main",
                "workflow": "executor",
                "files_changed": 2,
                "rec_id": "rec-1",
                "outcome": "success",
                "end_time": "2026-04-01T11:00:00",
            },
            {
                "branch": "main",
                "workflow": "executor",
                "files_changed": 2,
                "rec_id": "rec-1",
                "outcome": "success",
                "end_time": "2026-04-01T11:00:30",
            },
        ]
        tel_path = tmp_path / ".session-telemetry.jsonl"
        retro_path = tmp_path / ".retro-lite-log.jsonl"
        archive_dir = tmp_path / "archive"
        _make_jsonl(tel_path, entries)
        _make_jsonl(retro_path, [])

        with (
            patch.object(mod, "TELEMETRY_FILE", tel_path),
            patch.object(mod, "RETRO_FILE", retro_path),
            patch.object(mod, "ARCHIVE_DIR", archive_dir),
            patch(
                "argparse.ArgumentParser.parse_args",
                return_value=type(
                    "Args",
                    (),
                    {"dry_run": False},
                )(),
            ),
        ):
            main()
            first_result = _load_jsonl(tel_path)
            main()
            second_result = _load_jsonl(tel_path)

        assert first_result == second_result
        assert len(first_result) == 1
        assert first_result[0]["rec_id"] == "rec-1"
