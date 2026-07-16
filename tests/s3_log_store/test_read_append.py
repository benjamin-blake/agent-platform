"""Tests for scripts/s3_log_store.py -- backend-selection + read/append/list concern (VERBATIM
split from tests/test_s3_log_store.py, rec-2709 Wave 12).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.s3_log_store as store_mod
from scripts.s3_log_store import append_jsonl, get_backend, list_keys, read_jsonl


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
