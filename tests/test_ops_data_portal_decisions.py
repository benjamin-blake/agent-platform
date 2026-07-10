"""Tests for file_decision / update_decision and the decision reader fetch in ops_data_portal.

Decision 84: decision numbering authority is DECISIONS.md (caller supplies decision_id);
writes transit _ducklake_write (write_ops / update_ops); the offline decisions outbox and
the DynamoDB allocator are retired.

Decision 124 namespace migration: file_decision/update_decision/backfill_decisions_from_md
and _fetch_decision_from_reader moved to scripts/ops_portal/decisions.py, which imports
_ducklake_write, DECISIONS_JSONL, _sync_table, and _load_write_time_validators into its OWN
module namespace (a plain `from ... import` creates a separate binding from the facade's
re-exported copy). Patches therefore target scripts.ops_portal.decisions.<sym> -- the
namespace decisions.py's callers actually resolve at call time -- not the facade.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VALID_FIELDS = {
    "title": "Test Decision",
    "status": "Decided",
    "problem": "A test problem",
    "decision_text": "We decided to test this.",
    "context": "Context for this test decision",
}


class TestFileDecision:
    """Tests for file_decision() -- caller-keyed write_ops upsert."""

    def test_decision_id_field_returns_dec_id(self, tmp_path: Path) -> None:
        """file_decision() forms dec-NNN from fields['decision_id'] and writes via write_ops."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision({**_VALID_FIELDS, "decision_id": 73})

        assert result == "dec-073"
        mock_write.assert_called_once()
        table, record = mock_write.call_args[0]
        assert table == "ops_decisions"
        assert mock_write.call_args.kwargs["action"] == "write_ops"
        assert record["id"] == "dec-073"
        assert record["decision_id"] == 73

    def test_dual_write_in_record(self, tmp_path: Path) -> None:
        """file_decision() sets both id and decision_id on the written record."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision({**_VALID_FIELDS, "decision_id": 10})

        assert result == "dec-010"
        lines = decisions_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["id"] == "dec-010"
        assert entry["decision_id"] == 10

    def test_migration_int_id_supplies_number(self, tmp_path: Path) -> None:
        """_migration_int_id supplies the integer on the backfill path and preserves it."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_FIELDS), _migration_int_id=42)

        assert result == "dec-042"
        lines = decisions_jsonl.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["id"] == "dec-042"
        assert entry["decision_id"] == 42

    def test_missing_decision_id_raises(self) -> None:
        """Without decision_id or _migration_int_id, file_decision raises ValueError (Decision 84 I-2)."""
        with patch("scripts.ops_portal.decisions._ducklake_write") as mock_write:
            from scripts.ops_data_portal import file_decision

            with pytest.raises(ValueError, match="DECISIONS.md-assigned integer"):
                file_decision(dict(_VALID_FIELDS))

        mock_write.assert_not_called()

    def test_writer_failure_raises_loudly_no_outbox(self, tmp_path: Path) -> None:
        """A writer failure propagates -- there is no decisions outbox and no 'pending-' return."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"

        with (
            patch(
                "scripts.ops_portal.decisions._ducklake_write",
                side_effect=RuntimeError("ducklake_writer write_ops ops_decisions failed (HTTP 500)"),
            ),
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            with pytest.raises(RuntimeError, match="ducklake_writer"):
                file_decision({**_VALID_FIELDS, "decision_id": 99})

        assert not decisions_jsonl.exists()  # nothing written through on failure


class TestUpdateDecision:
    """Tests for update_decision() -- reader fetch + update_ops write."""

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
            patch("scripts.ops_portal.decisions._fetch_decision_from_reader", return_value=existing),
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
        ):
            from scripts.ops_data_portal import update_decision

            result = update_decision("dec-001", {"status": "Superseded"})

        assert result is True
        assert mock_write.call_args.kwargs["action"] == "update_ops"

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
            patch("scripts.ops_portal.decisions._fetch_decision_from_reader", return_value=existing),
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table"),
        ):
            from scripts.ops_data_portal import update_decision

            result = update_decision("dec-072", {"context": "updated context"})

        assert result is True


class TestRetiredDecisionsOutbox:
    """Decision 84 I-4: drain_pending_decisions and the decisions outbox are gone."""

    def test_drain_pending_decisions_absent(self) -> None:
        import scripts.ops_data_portal as portal

        assert not hasattr(portal, "drain_pending_decisions")
        assert not hasattr(portal, "_DECISIONS_PENDING_OUTBOX")


class TestFetchDecisionFromReader:
    """Tests for the decision_by_id named verb fetch (Decision 84 I-3)."""

    _DEC_ROW = {
        "id": "dec-007",
        "decision_id": 7,
        "title": "Test decision",
        "status": "Decided",
        "context": "ctx",
        "created_timestamp": "2026-05-01T00:00:00Z",
        "last_updated_timestamp": "2026-05-01T00:00:00Z",
    }

    def test_reader_path_returns_decision(self) -> None:
        """named('decision_by_id') success -> returns sanitised decision record."""
        reader = MagicMock()
        reader.named.return_value = [dict(self._DEC_ROW)]

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_decision_from_athena

            result = _fetch_decision_from_athena("dec-007")

        assert result is not None
        assert result["id"] == "dec-007"
        assert result["status"] == "Decided"
        reader.named.assert_called_once_with("decision_by_id", id="dec-007")

    def test_reader_failure_loud_fails_no_athena_fallback(self) -> None:
        """Reader failure propagates -- the Athena fallback retired with the estate (Decision 84 I-1)."""
        reader = MagicMock()
        reader.named.side_effect = RuntimeError("ducklake_reader 'named_read' failed (HTTP 500)")

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_decision_from_athena

            with pytest.raises(RuntimeError, match="ducklake_reader"):
                _fetch_decision_from_athena("dec-007")

    def test_reader_returns_none_when_decision_not_found(self) -> None:
        """Reader returns empty list -> function returns None."""
        reader = MagicMock()
        reader.named.return_value = []

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_decision_from_athena

            result = _fetch_decision_from_athena("dec-999")

        assert result is None

    def test_invalid_decision_id_raises_value_error(self) -> None:
        """Malformed decision_id raises ValueError before any reader call."""
        from scripts.ops_data_portal import _fetch_decision_from_athena

        with pytest.raises(ValueError, match="invalid decision_id"):
            _fetch_decision_from_athena("not-a-decision")
