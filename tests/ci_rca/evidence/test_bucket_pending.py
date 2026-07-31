"""bucket resolution + pending-write + upload-persist concern:
tests/ci_rca/evidence/test_bucket_pending.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestResolveBucket, TestWritePending,
TestUploadAndPersist. Patches scripts.ci_rca.evidence._upload_to_s3 (the S3 client is never
touched directly here -> no heavy-dep marker needed).
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.ci_rca.evidence import _resolve_bucket, _upload_to_s3, _write_pending, upload_and_persist


class TestResolveBucket:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("S3_LOG_BUCKET", "my-bucket")
        assert _resolve_bucket() == "my-bucket"

    def test_env_override_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("S3_LOG_BUCKET", "  my-bucket  ")
        assert _resolve_bucket() == "my-bucket"

    def test_returns_string_without_env(self, monkeypatch):
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        result = _resolve_bucket()
        assert isinstance(result, str)

    def test_config_value_and_config_failure_fallback(self, monkeypatch, tmp_path):
        import scripts.ci_rca.evidence as ev_mod

        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        config = type("Config", (), {"get": lambda self, _key, _default: "configured-bucket"})
        monkeypatch.setitem(sys.modules, "src.common.config", SimpleNamespace(Config=config))
        assert _resolve_bucket() == "configured-bucket"

        config = type("Config", (), {"__init__": lambda self: (_ for _ in ()).throw(RuntimeError("bad config"))})
        monkeypatch.setitem(sys.modules, "src.common.config", SimpleNamespace(Config=config))
        personal = tmp_path / "config" / "config.personal.yaml"
        personal.parent.mkdir()
        personal.write_text("aws:\n  s3_agent_logs_bucket: personal-bucket\n", encoding="utf-8")
        monkeypatch.setattr(ev_mod, "ROOT", tmp_path)
        assert _resolve_bucket() == "personal-bucket"

        personal.write_text("- invalid-shape\n", encoding="utf-8")
        assert _resolve_bucket() == ""


def test_upload_to_s3_selects_profile_and_puts_json(monkeypatch):
    client = SimpleNamespace(put_object=lambda **kwargs: setattr(client, "kwargs", kwargs))
    session_calls = []
    boto3 = SimpleNamespace(
        Session=lambda **kwargs: session_calls.append(kwargs) or SimpleNamespace(client=lambda *_args, **_kwargs: client)
    )
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setenv("AWS_PROFILE", "profile")
    _upload_to_s3(b"{}", "bucket", "key")
    assert session_calls == [{"profile_name": "profile"}]
    assert client.kwargs["ContentType"] == "application/json"


class TestWritePending:
    def test_creates_file(self, tmp_path):
        import scripts.ci_rca.evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"a": 1, "sha256": "abc123"}
            dest = _write_pending(bundle, "abc123")
            assert dest.exists()
            data = json.loads(dest.read_bytes())
            assert data["a"] == 1
        finally:
            ev_mod._PENDING_DIR = original


class TestUploadAndPersist:
    def test_successful_upload(self, tmp_path):
        bundle = {"sha256": "a" * 64, "data": "x"}
        with patch("scripts.ci_rca.evidence._upload_to_s3") as mock_up:
            result = upload_and_persist(bundle, "my-bucket")
        assert result["upload_status"] == "ok"
        assert "my-bucket" in result["s3_uri"]
        mock_up.assert_called_once()

    def test_upload_failure_writes_pending(self, tmp_path):
        import scripts.ci_rca.evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"sha256": "b" * 64, "data": "y"}
            with patch("scripts.ci_rca.evidence._upload_to_s3", side_effect=Exception("S3 down")):
                result = upload_and_persist(bundle, "my-bucket")
            assert result["upload_status"] == "upload_failed"
            assert result["s3_uri"] == ""
            assert Path(result["pending_path"]).exists()
        finally:
            ev_mod._PENDING_DIR = original

    def test_empty_bucket_writes_pending(self, tmp_path):
        import scripts.ci_rca.evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"sha256": "c" * 64}
            result = upload_and_persist(bundle, "")
            assert result["upload_status"] == "upload_failed"
        finally:
            ev_mod._PENDING_DIR = original
