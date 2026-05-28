"""Unit tests for scripts/s3_log_store.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.s3_log_store as store_mod
from scripts.s3_log_store import (
    append_jsonl,
    get_backend,
    list_agent_findings,
    list_keys,
    overwrite_jsonl,
    read_all_agent_findings,
    read_jsonl,
    write_timestamped_findings,
)


class TestGetBackend:
    """Tests for get_backend()."""

    def test_returns_local_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        assert get_backend() == "local"

    def test_returns_local_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "")
        assert get_backend() == "local"

    def test_returns_s3_when_env_set_and_boto3_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "my-test-bucket")
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            assert get_backend() == "s3"

    def test_returns_local_when_env_set_but_boto3_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "my-test-bucket")
        with patch.object(store_mod, "_BOTO3_AVAILABLE", False):
            assert get_backend() == "local"


class TestReadJsonlLocal:
    """Tests for read_jsonl() in local mode."""

    def test_reads_valid_jsonl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "test.jsonl"
        log_file.write_text('{"id": "1"}\n{"id": "2"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = read_jsonl("test.jsonl")
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_returns_empty_for_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = read_jsonl("missing.jsonl")
        assert result == []

    def test_skips_comment_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "test.jsonl"
        log_file.write_text('# schema comment\n{"id": "1"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = read_jsonl("test.jsonl")
        assert result == [{"id": "1"}]

    def test_skips_malformed_json_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "test.jsonl"
        log_file.write_text('bad json\n{"id": "2"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = read_jsonl("test.jsonl")
        assert result == [{"id": "2"}]

    def test_returns_empty_for_empty_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "empty.jsonl"
        log_file.write_text("", encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = read_jsonl("empty.jsonl")
        assert result == []


class TestAppendJsonlLocal:
    """Tests for append_jsonl() in local mode."""

    def test_appends_to_existing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "out.jsonl"
        log_file.write_text('{"id": "1"}\n', encoding="utf-8")
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = append_jsonl("out.jsonl", {"id": "2"})
        assert result is True
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1]) == {"id": "2"}

    def test_creates_file_if_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = append_jsonl("new.jsonl", {"id": "1"})
        assert result is True
        assert (log_dir / "new.jsonl").exists()
        data = json.loads((log_dir / "new.jsonl").read_text(encoding="utf-8").strip())
        assert data == {"id": "1"}

    def test_returns_false_on_write_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            with patch("builtins.open", side_effect=OSError("disk full")):
                result = append_jsonl("out.jsonl", {"id": "1"})
        assert result is False

    def test_pytest_current_test_gate_skips_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        target = log_dir / "tmp" / "rec-360.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            result = append_jsonl("tmp/rec-360.jsonl", {"x": 1})
        assert result is True
        assert not target.exists()


class TestListKeysLocal:
    """Tests for list_keys() in local mode."""

    def test_lists_matching_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "a.jsonl").touch()
        (log_dir / "b.jsonl").touch()
        (log_dir / "c.txt").touch()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            keys = list_keys("*.jsonl")
        assert sorted(keys) == ["a.jsonl", "b.jsonl"]

    def test_returns_empty_when_no_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        with patch.object(store_mod, "_LOGS_DIR", log_dir):
            keys = list_keys("*.jsonl")
        assert keys == []


class TestReadJsonlS3:
    """Tests for read_jsonl() in S3 mode."""

    def _make_s3_mock(self, body: str) -> MagicMock:
        client = MagicMock()
        client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=body.encode()))}
        return client

    def test_reads_from_s3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        mock_client = self._make_s3_mock('{"id": "1"}\n{"id": "2"}\n')
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                result = read_jsonl("recs.jsonl")
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_returns_empty_for_no_such_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        error = Exception("NoSuchKey")
        error.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
        mock_client = MagicMock()
        mock_client.get_object.side_effect = error
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                result = read_jsonl("missing.jsonl")
        assert result == []


class TestAppendJsonlS3:
    """Tests for append_jsonl() in S3 mode."""

    def test_appends_to_s3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        existing = '{"id": "1"}\n'
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=existing.encode()))}
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                result = append_jsonl("log.jsonl", {"id": "2"})
        assert result is True
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        body_text = call_kwargs["Body"].decode("utf-8")
        lines = body_text.strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1]) == {"id": "2"}

    def test_creates_new_file_in_s3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S3_LOG_BUCKET", "test-bucket")
        error = Exception("NoSuchKey")
        error.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
        mock_client = MagicMock()
        mock_client.get_object.side_effect = error
        with patch.object(store_mod, "_BOTO3_AVAILABLE", True):
            with patch.object(store_mod, "_get_s3_client", return_value=mock_client):
                result = append_jsonl("new.jsonl", {"id": "1"})
        assert result is True
        mock_client.put_object.assert_called_once()


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


# ---------------------------------------------------------------------------
# OpsWriter write-through tests (Decision 50)
# ---------------------------------------------------------------------------


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
