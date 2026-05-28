"""Tests for file_decision, update_decision, drain_pending_decisions in ops_data_portal."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

_VALID_FIELDS = {
    "title": "Test Decision",
    "status": "Decided",
    "problem": "A test problem",
    "decision_text": "We decided to test this.",
    "context": "Context for this test decision",
}


class TestFileDecision:
    """Tests for file_decision() (D7)."""

    def test_allocator_path_returns_dec_id(self, tmp_path: Path) -> None:
        """file_decision() allocates via DynamoDB and returns dec-NNN string."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id", return_value=73),
            patch("scripts.ops_data_portal.OpsWriter") as mock_ow,
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_FIELDS))

        assert result == "dec-073"
        mock_ow.return_value.write.assert_called_once()
        table, record = mock_ow.return_value.write.call_args[0]
        assert table == "ops_decisions"
        assert record["id"] == "dec-073"
        assert record["decision_id"] == 73

    def test_dual_write_in_record(self, tmp_path: Path) -> None:
        """file_decision() sets both id and decision_id on the staged record."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id", return_value=10),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_FIELDS))

        assert result == "dec-010"
        lines = decisions_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["id"] == "dec-010"
        assert entry["decision_id"] == 10

    def test_migration_int_id_bypass_allocator(self, tmp_path: Path) -> None:
        """_migration_int_id bypasses DynamoDB allocator and preserves the integer."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id") as mock_next_id,
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_FIELDS), _migration_int_id=42)

        mock_next_id.assert_not_called()
        assert result == "dec-042"
        lines = decisions_jsonl.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["id"] == "dec-042"
        assert entry["decision_id"] == 42

    def test_offline_queues_to_outbox(self, tmp_path: Path) -> None:
        """file_decision() queues to outbox when DynamoDB is unreachable."""
        pending_dir = tmp_path / "pending"

        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("DynamoDB down")),
            patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", pending_dir),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_FIELDS))

        assert result.startswith("pending-")
        files = list(pending_dir.glob("*.json"))
        assert len(files) == 1
        queued = json.loads(files[0].read_text(encoding="utf-8"))
        assert "id" not in queued
        assert queued["title"] == _VALID_FIELDS["title"]

    def test_outbox_preserves_migration_int_id(self, tmp_path: Path) -> None:
        """When the write sequence fails, _migration_int_id is preserved in the queued JSON.

        _migration_int_id bypasses _next_id, so the outbox path is triggered by
        an OpsWriter failure rather than a DynamoDB allocator failure.
        """
        pending_dir = tmp_path / "pending"

        with (
            patch("scripts.ops_data_portal.OpsWriter") as mock_ow,
            patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            mock_ow.return_value.write.side_effect = RuntimeError("OpsWriter down")
            from scripts.ops_data_portal import file_decision

            file_decision(dict(_VALID_FIELDS), _migration_int_id=99)

        files = list(pending_dir.glob("*.json"))
        assert len(files) == 1
        queued = json.loads(files[0].read_text(encoding="utf-8"))
        assert queued["_migration_int_id"] == 99


class TestUpdateDecision:
    """Tests for update_decision() (D7, D4 gate removed after backfill)."""

    def test_returns_true_on_success(self, tmp_path: Path) -> None:
        """update_decision returns True when the write sequence succeeds."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        existing = {
            "id": "dec-001",
            "decision_id": 1,
            "title": "Existing Decision",
            "status": "Decided",
            "created_timestamp": "2026-05-13T12:00:00Z",
            "last_updated_timestamp": "2026-05-13T12:00:00Z",
        }

        with (
            patch("scripts.ops_data_portal._fetch_decision_from_athena", return_value=existing),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import update_decision

            result = update_decision("dec-001", {"status": "Superseded"})

        assert result is True

    def test_str_arg_accepted(self, tmp_path: Path) -> None:
        """update_decision accepts a str decision_id (not int)."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        existing = {
            "id": "dec-072",
            "decision_id": 72,
            "title": "Test",
            "status": "Decided",
            "created_timestamp": "2026-05-13T12:00:00Z",
            "last_updated_timestamp": "2026-05-13T12:00:00Z",
        }

        with (
            patch("scripts.ops_data_portal._fetch_decision_from_athena", return_value=existing),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import update_decision

            result = update_decision("dec-072", {"context": "updated context"})

        assert result is True


class TestDrainPendingDecisions:
    """Tests for drain_pending_decisions() (D7)."""

    def test_no_outbox_returns_empty(self, tmp_path: Path) -> None:
        """drain_pending_decisions returns zeros when outbox dir is absent."""
        missing = tmp_path / "nonexistent"
        with patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", missing):
            from scripts.ops_data_portal import drain_pending_decisions

            result = drain_pending_decisions()
        assert result == {"drained": 0, "skipped": 0}

    def test_drain_standard_pending_file(self, tmp_path: Path) -> None:
        """drain_pending_decisions successfully drains a queued file."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        pending_fields = dict(_VALID_FIELDS)
        (pending_dir / "abc123.json").write_text(json.dumps(pending_fields), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value=5),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import drain_pending_decisions

            result = drain_pending_decisions()

        assert result["drained"] == 1
        assert result["skipped"] == 0
        assert not list(pending_dir.glob("*.json"))

    def test_drain_preserves_migration_int_id(self, tmp_path: Path) -> None:
        """drain_pending_decisions honours _migration_int_id from the queued JSON."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        pending_fields = {**_VALID_FIELDS, "_migration_int_id": 37}
        (pending_dir / "mig.json").write_text(json.dumps(pending_fields), encoding="utf-8")

        def fake_next_id(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("_next_id must not be called when _migration_int_id is set")

        with (
            patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", side_effect=fake_next_id),
            patch("scripts.ops_data_portal.OpsWriter") as mock_ow,
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import drain_pending_decisions

            result = drain_pending_decisions()
            table, record = mock_ow.return_value.write.call_args[0]

        assert result["drained"] == 1
        assert record["id"] == "dec-037"
        assert record["decision_id"] == 37
