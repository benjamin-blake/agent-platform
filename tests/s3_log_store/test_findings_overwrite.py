"""Tests for scripts/s3_log_store.py -- timestamped-findings + agent-findings listing + overwrite
concern (VERBATIM split from tests/test_s3_log_store.py, rec-2709 Wave 12).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.s3_log_store as store_mod
from scripts.s3_log_store import (
    list_agent_findings,
    overwrite_jsonl,
    read_all_agent_findings,
    write_timestamped_findings,
)


class TestWriteTimestampedFindings:
    """Tests for write_timestamped_findings()."""

    def test_writes_to_correct_local_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        findings = [{"title": "issue1"}, {"title": "issue2"}]
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            key = write_timestamped_findings("doc-freshness", findings)

        assert key.startswith("agents/doc-freshness/")
        assert key.endswith(".jsonl")
        path = log_dir / key
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"title": "issue1"}

    def test_returns_empty_string_on_local_write_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            with patch("builtins.open", side_effect=OSError("permission denied")):
                key = write_timestamped_findings("orphan-code", [{"x": 1}])
        assert key == ""

    def test_writes_to_s3_with_correct_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        mock_client = MagicMock()
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                key = write_timestamped_findings("code-smell", [{"f": "foo.py"}])

        assert key.startswith("agents/code-smell/")
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == key

    def test_returns_empty_string_on_s3_write_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("S3 error")
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                key = write_timestamped_findings("doc-freshness", [{"x": 1}])
        assert key == ""

    def test_writes_empty_findings_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            key = write_timestamped_findings("doc-freshness", [])
        assert key.startswith("agents/doc-freshness/")
        path = log_dir / key
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""


class TestListAgentFindings:
    """Tests for list_agent_findings()."""

    def test_lists_all_agents_when_no_filter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        (log_dir / "agents" / "doc-freshness").mkdir(parents=True)
        (log_dir / "agents" / "orphan-code").mkdir(parents=True)
        (log_dir / "agents" / "doc-freshness" / "2026-04-07T06-00-00Z.jsonl").touch()
        (log_dir / "agents" / "orphan-code" / "2026-04-08T06-00-00Z.jsonl").touch()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            keys = list_agent_findings()
        assert any("doc-freshness" in k for k in keys)
        assert any("orphan-code" in k for k in keys)

    def test_scopes_to_specific_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        (log_dir / "agents" / "doc-freshness").mkdir(parents=True)
        (log_dir / "agents" / "orphan-code").mkdir(parents=True)
        (log_dir / "agents" / "doc-freshness" / "2026-04-07T06-00-00Z.jsonl").touch()
        (log_dir / "agents" / "orphan-code" / "2026-04-08T06-00-00Z.jsonl").touch()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            keys = list_agent_findings("doc-freshness")
        assert all("doc-freshness" in k for k in keys)
        assert not any("orphan-code" in k for k in keys)

    def test_returns_empty_when_no_findings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            keys = list_agent_findings()
        assert keys == []


class TestReadAllAgentFindings:
    """Tests for read_all_agent_findings()."""

    def test_reads_all_findings_with_source_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        f1 = log_dir / "agents" / "doc-freshness" / "2026-04-07T06-00-00Z.jsonl"
        f2 = log_dir / "agents" / "orphan-code" / "2026-04-08T06-00-00Z.jsonl"
        f1.parent.mkdir(parents=True)
        f2.parent.mkdir(parents=True)
        f1.write_text('{"title": "stale doc"}\n', encoding="utf-8")
        f2.write_text('{"title": "orphan fn"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            results = read_all_agent_findings()
        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert titles == {"stale doc", "orphan fn"}
        for item in results:
            assert "source" in item

    def test_source_contains_agent_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        f1 = log_dir / "agents" / "code-smell" / "2026-04-09T06-00-00Z.jsonl"
        f1.parent.mkdir(parents=True)
        f1.write_text('{"title": "deep nesting"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            results = read_all_agent_findings()
        assert results[0]["source"].startswith("code-smell/")

    def test_does_not_overwrite_existing_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        f1 = log_dir / "agents" / "doc-freshness" / "2026-04-07T06-00-00Z.jsonl"
        f1.parent.mkdir(parents=True)
        f1.write_text('{"title": "stale", "source": "custom-source"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            results = read_all_agent_findings()
        assert results[0]["source"] == "custom-source"

    def test_returns_empty_when_no_keys(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            results = read_all_agent_findings()
        assert results == []


class TestOverwriteJsonl:
    """Tests for overwrite_jsonl()."""

    def test_local_write_creates_file_with_correct_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        entries = [{"rank": 1, "rec_id": "rec-001"}, {"rank": 2, "rec_id": "rec-002"}]
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = overwrite_jsonl("out.jsonl", entries)
        assert result is True
        lines = (log_dir / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"rank": 1, "rec_id": "rec-001"}
        assert json.loads(lines[1]) == {"rank": 2, "rec_id": "rec-002"}

    def test_local_write_overwrites_existing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        existing = log_dir / "out.jsonl"
        existing.write_text('{"rank": 99, "rec_id": "old"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        entries = [{"rank": 1, "rec_id": "rec-new"}]
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = overwrite_jsonl("out.jsonl", entries)
        assert result is True
        lines = existing.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"rank": 1, "rec_id": "rec-new"}

    def test_local_write_empty_entries_creates_empty_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = overwrite_jsonl("empty.jsonl", [])
        assert result is True
        assert (log_dir / "empty.jsonl").read_text(encoding="utf-8") == ""

    def test_s3_path_calls_put_object_with_correct_key_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        mock_client = MagicMock()
        entries = [{"rank": 1, "rec_id": "rec-001"}]
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                result = overwrite_jsonl("priority-queue/.priority-queue.jsonl", entries)
        assert result is True
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "priority-queue/.priority-queue.jsonl"
        body_text = call_kwargs["Body"].decode("utf-8")
        assert json.loads(body_text.strip()) == {"rank": 1, "rec_id": "rec-001"}

    def test_pytest_current_test_guard_skips_local_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        target = log_dir / "priority-queue" / ".priority-queue.jsonl"
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = overwrite_jsonl("priority-queue/.priority-queue.jsonl", [{"rank": 1}])
        assert result is True
        assert not target.exists()
