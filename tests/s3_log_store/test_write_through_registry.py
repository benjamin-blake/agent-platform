"""Tests for scripts/s3_log_store.py -- OpsWriter write-through (Decision 50) + log-storage YAML
registry (T-1.15) concern (VERBATIM split from tests/test_s3_log_store.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.s3_log_store as store_mod


class TestOpsWriterWriteThrough:
    """Tests for ops_writer write-through routing added to s3_log_store."""

    def test_append_jsonl_does_not_route_recommendations_key_to_ops_writer(self, monkeypatch, tmp_path):
        """append_jsonl does NOT route .recommendations-log.jsonl to ops_writer (routing removed in dq-ops-rec-enforcement)."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import append_jsonl

            result = append_jsonl(".recommendations-log.jsonl", {"id": "rec-001"})

        assert result is True
        mock_ops.write.assert_not_called()

    def test_append_jsonl_calls_ops_write_for_execution_plans_key(self, monkeypatch, tmp_path):
        """append_jsonl calls ops_writer.write for .execution-plans.jsonl key."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import append_jsonl

            result = append_jsonl(".execution-plans.jsonl", {"plan_id": "p-1"})

        assert result is True
        mock_ops.write.assert_called_once_with("ops_execution_plans", {"plan_id": "p-1"})

    def test_append_jsonl_calls_ops_write_for_session_telemetry_key(self, monkeypatch, tmp_path):
        """append_jsonl calls ops_writer.write for .session-telemetry.jsonl key."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import append_jsonl

            result = append_jsonl(".session-telemetry.jsonl", {"session_id": "s-1"})

        assert result is True
        mock_ops.write.assert_called_once_with("ops_session_log", {"session_id": "s-1"})

    def test_append_jsonl_does_not_call_ops_write_for_unmapped_key(self, monkeypatch, tmp_path):
        """append_jsonl does NOT call ops_writer.write for unmapped keys."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import append_jsonl

            append_jsonl(".retro-lite-log.jsonl", {"friction": "clean"})

        mock_ops.write.assert_not_called()

    def test_overwrite_jsonl_calls_ops_write_for_priority_queue(self, monkeypatch, tmp_path):
        """overwrite_jsonl calls ops_writer.write for each entry in priority queue with shared queue_run_id."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "priority-queue").mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        entries = [{"rank": 1, "rec_id": "rec-001"}, {"rank": 2, "rec_id": "rec-002"}]

        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import overwrite_jsonl

            result = overwrite_jsonl("priority-queue/.priority-queue.jsonl", entries)

        assert result is True
        assert mock_ops.write.call_count == 2

        # Both calls must use the same queue_run_id
        call_args_list = mock_ops.write.call_args_list
        run_ids = {call[0][1].get("queue_run_id") for call in call_args_list}
        assert len(run_ids) == 1  # single shared queue_run_id

    def test_ops_write_through_failure_does_not_propagate(self, monkeypatch, tmp_path):
        """OpsWriter.write failure is caught and does not propagate from append_jsonl."""
        import scripts.s3_log_store as store_mod_local

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_ops = MagicMock()
        mock_ops.write.side_effect = RuntimeError("ops failure")

        with (
            patch.object(store_mod_local, "_LOGS_DIR", log_dir),
            patch.object(store_mod_local, "_get_ops_writer", return_value=mock_ops),
        ):
            from scripts.s3_log_store import append_jsonl

            # Must not raise
            result = append_jsonl(".recommendations-log.jsonl", {"id": "rec-001"})

        assert result is True  # local write succeeded even though ops failed


class TestLogStorageRegistry:
    """Tests for the lazy YAML loader and routing accessors in s3_log_store."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Save and restore the cached registry and contract path around each test."""
        original_registry = store_mod._LOG_STORAGE_REGISTRY
        original_path = store_mod._LOG_STORAGE_CONTRACT_PATH
        store_mod._LOG_STORAGE_REGISTRY = None
        yield
        store_mod._LOG_STORAGE_REGISTRY = original_registry
        store_mod._LOG_STORAGE_CONTRACT_PATH = original_path

    def test_reads_yaml(self, tmp_path: Path) -> None:
        """Loader reads the YAML contract and returns routing values from the file."""
        contract = tmp_path / "log-storage.yaml"
        contract.write_text(
            "routing:\n  ops_table_routing:\n    .foo.jsonl: foo_table\n  priority_queue_key: queue/key.jsonl\n",
            encoding="utf-8",
        )
        store_mod._LOG_STORAGE_CONTRACT_PATH = contract
        assert store_mod.get_ops_table_routing() == {".foo.jsonl": "foo_table"}
        assert store_mod.get_priority_queue_key() == "queue/key.jsonl"

    def test_anti_drift(self) -> None:
        """YAML routing block equals the in-code fallback constants (no silent divergence)."""
        import yaml  # noqa: PLC0415

        doc = yaml.safe_load(store_mod._LOG_STORAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
        assert store_mod.FALLBACK_OPS_TABLE_ROUTING == doc["routing"]["ops_table_routing"]
        assert store_mod.FALLBACK_PRIORITY_QUEUE_KEY == doc["routing"]["priority_queue_key"]

    def test_absent_yaml_fallback(self, tmp_path: Path) -> None:
        """Returns fallback constants when the contract file does not exist."""
        store_mod._LOG_STORAGE_CONTRACT_PATH = tmp_path / "does-not-exist.yaml"
        assert store_mod.get_ops_table_routing() == store_mod.FALLBACK_OPS_TABLE_ROUTING
        assert store_mod.get_priority_queue_key() == store_mod.FALLBACK_PRIORITY_QUEUE_KEY

    def test_unparseable_yaml_fallback(self, tmp_path: Path) -> None:
        """Returns fallback constants when the contract file contains invalid YAML."""
        contract = tmp_path / "log-storage.yaml"
        contract.write_text("}{invalid yaml{", encoding="utf-8")
        store_mod._LOG_STORAGE_CONTRACT_PATH = contract
        assert store_mod.get_ops_table_routing() == store_mod.FALLBACK_OPS_TABLE_ROUTING
        assert store_mod.get_priority_queue_key() == store_mod.FALLBACK_PRIORITY_QUEUE_KEY

    def test_yaml_import_unavailable_fallback(self) -> None:
        """Returns fallback constants when yaml is not importable (Lambda runtime safety)."""
        import sys  # noqa: PLC0415

        original_yaml = sys.modules.get("yaml")
        sys.modules["yaml"] = None  # type: ignore[assignment]
        try:
            assert store_mod.get_ops_table_routing() == store_mod.FALLBACK_OPS_TABLE_ROUTING
            assert store_mod.get_priority_queue_key() == store_mod.FALLBACK_PRIORITY_QUEUE_KEY
        finally:
            if original_yaml is not None:
                sys.modules["yaml"] = original_yaml
            else:
                del sys.modules["yaml"]
