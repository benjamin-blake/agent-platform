"""Tests for src/data/handlers/ops_compaction_handler.py."""

from __future__ import annotations

import sys
from importlib import import_module, reload
from unittest.mock import MagicMock, patch

_VALID_TABLES = [
    "ops_recommendations",
    "ops_execution_plans",
    "ops_session_log",
    "ops_decisions",
    "ops_priority_queue",
]


def _make_s3_event(key: str) -> dict:
    return {"Records": [{"s3": {"object": {"key": key}}}]}


def _get_handler():
    """Return handler function, reloading module to pick up fresh patches."""
    mod_name = "src.data.handlers.ops_compaction_handler"
    if mod_name in sys.modules:
        mod = reload(sys.modules[mod_name])
    else:
        mod = import_module(mod_name)
    return mod.handler


class TestOpsCompactionHandlerS3Event:
    """Tests for S3 event key parsing path."""

    def test_parses_key_and_calls_compact(self) -> None:
        """Well-formed S3 key for a non-recs table: table and trade_date extracted, compact() called."""
        key = "staging/ops_decisions/dt=2026-04-21/batch-abc.jsonl"
        mock_writer = MagicMock()
        mock_writer.compact.return_value = 5

        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler(_make_s3_event(key), None)

        mock_writer.compact.assert_called_once_with("ops_decisions", "2026-04-21")
        assert result["statusCode"] == 200
        assert result["rows_compacted"] == 5
        assert result["table"] == "ops_decisions"
        assert result["trade_date"] == "2026-04-21"

    def test_unknown_table_returns_zero_without_compact(self) -> None:
        """Unknown table name logs warning and returns rows_compacted=0 without calling compact."""
        key = "staging/unknown_table/dt=2026-04-21/batch-xyz.jsonl"
        mock_writer = MagicMock()

        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler(_make_s3_event(key), None)

        mock_writer.compact.assert_not_called()
        assert result["statusCode"] == 200
        assert result["rows_compacted"] == 0

    def test_malformed_s3_event_returns_400(self) -> None:
        """Missing Records key returns statusCode 400."""
        mock_writer = MagicMock()
        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler({}, None)

        assert result["statusCode"] == 400
        assert result["rows_compacted"] == 0


class TestOpsCompactionHandlerForceEvent:
    """Tests for force_table / force_date manual invocation path."""

    def test_force_event_skips_s3_parsing(self) -> None:
        """force_table + force_date bypass S3 key parsing and call compact directly."""
        mock_writer = MagicMock()
        mock_writer.compact.return_value = 12

        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler(
                {"force_table": "ops_session_log", "force_date": "2026-04-20"},
                None,
            )

        mock_writer.compact.assert_called_once_with("ops_session_log", "2026-04-20")
        assert result["statusCode"] == 200
        assert result["rows_compacted"] == 12
        assert result["table"] == "ops_session_log"
        assert result["trade_date"] == "2026-04-20"

    def test_force_event_unknown_table_returns_zero(self) -> None:
        """force_table with unknown name returns rows_compacted=0 without calling compact."""
        mock_writer = MagicMock()

        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler(
                {"force_table": "not_a_real_table", "force_date": "2026-04-20"},
                None,
            )

        mock_writer.compact.assert_not_called()
        assert result["rows_compacted"] == 0

    def test_valid_table_returns_compact_row_count(self) -> None:
        """compact() return value is surfaced as rows_compacted."""
        mock_writer = MagicMock()
        mock_writer.compact.return_value = 42

        with (
            patch("scripts.ops_writer.OpsWriter", return_value=mock_writer),
            patch(
                "src.data.handlers.ops_compaction_handler.TABLE_NAMES",
                _VALID_TABLES,
            ),
        ):
            handler = _get_handler()
            result = handler(
                {"force_table": "ops_decisions", "force_date": "2026-04-21"},
                None,
            )

        assert result["rows_compacted"] == 42


class TestRecsExcludedFromCompaction:
    """ops_recommendations must be excluded from Iceberg compaction (T2.19 / Decision 81 cl.7)."""

    def test_recs_force_event_returns_early_with_note(self) -> None:
        """force_table=ops_recommendations -> early return, rows_compacted=0, note=recs_excluded_ducklake."""
        mock_writer = MagicMock()

        with patch("scripts.ops_writer.OpsWriter", return_value=mock_writer):
            handler = _get_handler()
            result = handler(
                {"force_table": "ops_recommendations", "force_date": "2026-04-21"},
                None,
            )

        assert result["rows_compacted"] == 0
        assert result.get("note") == "recs_excluded_ducklake"
        mock_writer.compact.assert_not_called()

    def test_recs_s3_event_returns_early_with_note(self) -> None:
        """S3 event targeting ops_recommendations prefix -> early return, no compact call."""
        mock_writer = MagicMock()
        event = _make_s3_event("staging/ops_recommendations/dt=2026-04-21/batch.jsonl")

        with patch("scripts.ops_writer.OpsWriter", return_value=mock_writer):
            handler = _get_handler()
            result = handler(event, None)

        assert result["rows_compacted"] == 0
        assert result.get("note") == "recs_excluded_ducklake"
        mock_writer.compact.assert_not_called()
