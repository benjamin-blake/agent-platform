"""DuckLakeReader (SigV4 Function-URL) concern of src/common/iceberg_reader.py (rec-2709 Wave 11).

T2.19: DuckLakeReader + make_reader factory + ops_storage_backend flag.

HEAVY-DEP MARKER MODULE: carries a module-level `import boto3  # noqa: F401` -- the
non-integration tests here assert the non-skipped SigV4 path, which needs boto3/requests/botocore
at runtime; the marker makes --collect-only fail so the fast tier proactively defers the whole
module (ops_writer precedent).

Split from tests/test_iceberg_reader.py (VERBATIM move).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import boto3  # noqa: F401
import pytest


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _patch_dl_invoke(monkeypatch, resp: _FakeResp, captured: dict):
    """Patch the DuckLakeReader SigV4 plumbing (boto3 + requests + profile) for a canned response."""
    import src.common.iceberg_reader as ir

    monkeypatch.setenv("DUCKLAKE_READER_URL", "https://reader.example/")

    class _Creds:
        access_key = "AK"
        secret_key = "SK"  # noqa: S105 -- fake fixture  # pragma: allowlist secret
        token = None

        def get_frozen_credentials(self):
            return self

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return _Creds()

    import boto3
    import requests
    from botocore.auth import SigV4Auth

    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)
    monkeypatch.setattr("scripts.aws_profile.resolve_aws_profile", lambda *a, **k: None)

    def _post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = data
        return resp

    monkeypatch.setattr(requests, "post", _post)
    return ir


def _patch_dl_invoke_seq(monkeypatch, responses: list, captured: dict):
    """Like _patch_dl_invoke but returns *responses* in sequence and stubs time.sleep (retry tests)."""
    import src.common.iceberg_reader as ir

    monkeypatch.setenv("DUCKLAKE_READER_URL", "https://reader.example/")

    class _Creds:
        access_key = "AK"
        secret_key = "SK"  # noqa: S105 -- fake fixture  # pragma: allowlist secret
        token = None

        def get_frozen_credentials(self):
            return self

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return _Creds()

    import boto3
    import requests
    from botocore.auth import SigV4Auth

    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)
    monkeypatch.setattr("scripts.aws_profile.resolve_aws_profile", lambda *a, **k: None)
    captured["sleeps"] = []
    monkeypatch.setattr(ir.time, "sleep", lambda s: captured["sleeps"].append(s))
    seq = list(responses)

    def _post(url, data=None, headers=None, timeout=None):
        captured["calls"] = captured.get("calls", 0) + 1
        return seq.pop(0)

    monkeypatch.setattr(requests, "post", _post)
    return ir


def test_ducklake_reader_retries_transient_502_then_succeeds(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke_seq(
        monkeypatch,
        [_FakeResp(status_code=502, text="Internal Server Error"), _FakeResp(payload={"rows": [{"v": 1}]})],
        captured,
    )
    rows = ir.DuckLakeReader().query("ops_recommendations", "SELECT COUNT(*) v FROM {tbl}")
    assert rows == [{"v": 1}]
    assert captured["calls"] == 2  # retried once after the cold-resume 502
    assert len(captured["sleeps"]) == 1


def test_ducklake_reader_persistent_502_raises_after_max_attempts(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke_seq(monkeypatch, [_FakeResp(status_code=502, text="boom")] * 3, captured)
    # query() swallows the loud-fail and returns None; the underlying _invoke exhausted retries.
    assert ir.DuckLakeReader().query("ops_recommendations", "SELECT 1 FROM {tbl}") is None
    assert captured["calls"] == 3  # _READER_MAX_ATTEMPTS
    assert len(captured["sleeps"]) == 2  # backoff between the 3 attempts


def test_ducklake_reader_non_transient_500_not_retried(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke_seq(monkeypatch, [_FakeResp(status_code=500, text="boom")], captured)
    assert ir.DuckLakeReader().query("ops_recommendations", "SELECT 1 FROM {tbl}") is None
    assert captured["calls"] == 1  # 500 is not transient -> no retry
    assert captured["sleeps"] == []


def test_ops_storage_backend_flag_retired():
    """Decision 84 I-1: the OPS_STORAGE_BACKEND rollback flag and its constants are deleted."""
    import src.common.iceberg_reader as ir

    for name in ("ops_storage_backend", "_OPS_STORAGE_BACKEND_ENV", "_OPS_BACKEND_DEFAULT"):
        assert not hasattr(ir, name), f"retired symbol still present: {name}"


def test_make_reader_always_returns_ducklake(monkeypatch):
    """make_reader() returns DuckLakeReader unconditionally -- the env flag has no effect."""
    import src.common.iceberg_reader as ir

    monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")  # ignored: the flag is retired
    assert isinstance(ir.make_reader(), ir.DuckLakeReader)
    monkeypatch.delenv("OPS_STORAGE_BACKEND", raising=False)
    assert isinstance(ir.make_reader(), ir.DuckLakeReader)


def test_make_reader_all_tables_route_to_ducklake():
    """Every ops table (and the table=None default) transits the DuckLake boundary (Decision 84 I-1)."""
    import src.common.iceberg_reader as ir

    for table in (None, "ops_recommendations", "ops_decisions", "ops_priority_queue"):
        assert isinstance(ir.make_reader(table=table), ir.DuckLakeReader), f"table={table!r}"


def test_make_reader_passes_profile_through():
    import src.common.iceberg_reader as ir

    reader = ir.make_reader(profile="agent_platform")
    assert isinstance(reader, ir.DuckLakeReader)
    assert reader._profile == "agent_platform"


def test_ducklake_reader_current_state_no_filter(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"id": "rec-1"}]}), captured)
    rows = ir.DuckLakeReader().current_state("ops_recommendations")
    assert rows == [{"id": "rec-1"}]
    import json as _json

    assert _json.loads(captured["body"])["action"] == "read_ops_current"


def test_ducklake_reader_query_uses_query_ops(monkeypatch):
    """The explicit query() path still routes arbitrary read-only SQL through query_ops."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"v": 0}]}), captured)
    ir.DuckLakeReader().query("ops_recommendations", "SELECT COUNT(*) v FROM {tbl}", params=("x",))
    import json as _json

    body = _json.loads(captured["body"])
    assert body["action"] == "query_ops"
    assert body["sql"] == "SELECT COUNT(*) v FROM {tbl}"
    assert body["params"] == ["x"]


def test_ducklake_reader_query_returns_none_on_error(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=500, text="boom"), captured)
    assert ir.DuckLakeReader().query("ops_recommendations", "SELECT 1 FROM {tbl}") is None


def test_ducklake_reader_latest_snapshot_is_none():
    import src.common.iceberg_reader as ir

    assert ir.DuckLakeReader().latest_snapshot("ops_recommendations") is None


def test_ducklake_reader_url_loud_fail_when_unset(monkeypatch):
    import src.common.iceberg_reader as ir

    monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
    monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", lambda *a, **k: None)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    # The AWS-API fallback also fails (no resolvable URL) -> the loud-fail must still fire.
    monkeypatch.setattr(ir, "_resolve_function_url_via_api", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="DUCKLAKE_READER_URL not set"):
        ir.DuckLakeReader()._reader_url()


def test_ducklake_reader_url_api_fallback(monkeypatch):
    """When env + terraform are unavailable, the reader URL resolves via GetFunctionUrlConfig (CI case)."""
    import src.common.iceberg_reader as ir

    monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
    monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", lambda *a, **k: None)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(
        ir, "_resolve_function_url_via_api", lambda name, profile=None, region="eu-west-2": "https://api.example/"
    )
    assert ir.DuckLakeReader()._reader_url() == "https://api.example"


def test_ducklake_reader_current_state_parameterizes_single_key(monkeypatch):
    """row_filter `id = 'rec-1'` becomes the structural {column, value} filter (rec-2170, no raw SQL)."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"id": "rec-1"}]}), captured)
    ir.DuckLakeReader().current_state("ops_recommendations", row_filter="id = 'rec-1'")
    import json as _json

    body = _json.loads(captured["body"])
    assert body == {
        "action": "read_ops_current",  # NOT query_ops -- parameterized, no raw SQL
        "table": "ops_recommendations",
        "filter": {"column": "id", "value": "rec-1"},
    }
    assert "key" not in body  # the legacy merge-key-only field is gone on this path


def test_ducklake_reader_current_state_non_key_filter_carries_column(monkeypatch):
    """Regression rec-2170: a non-merge-key filter sends ITS column, not the merge key.

    The previous form discarded the column and the reader bound the value against id,
    silently returning a false zero for any `status = '...'`-style filter.
    """
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"id": "rec-1", "status": "open"}]}), captured)
    rows = ir.DuckLakeReader().current_state("ops_recommendations", row_filter="status = 'open'")
    import json as _json

    body = _json.loads(captured["body"])
    assert body["filter"] == {"column": "status", "value": "open"}
    assert rows == [{"id": "rec-1", "status": "open"}]


def test_ducklake_reader_current_state_rejects_complex_filter(monkeypatch):
    """A non-single-key row_filter is rejected rather than raw-interpolated (injection guard)."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": []}), captured)
    with pytest.raises(ValueError, match="single-key equality"):
        ir.DuckLakeReader().current_state("ops_recommendations", row_filter="1=1 OR id IS NOT NULL")


def test_parse_single_key_filter():
    """_parse_single_key_filter returns the (column, value) pair, or None for non-matching shapes."""
    import src.common.iceberg_reader as ir

    assert ir._parse_single_key_filter("id = 'rec-1'") == ("id", "rec-1")
    assert ir._parse_single_key_filter("  status='open'  ") == ("status", "open")
    assert ir._parse_single_key_filter("1=1 OR 2=2") is None
    assert ir._parse_single_key_filter("id IN ('a','b')") is None


def test_ducklake_reader_named_posts_verb_and_params(monkeypatch):
    """named() POSTs {"action": "named_read", "verb": ..., "params": {...}} and returns body rows."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"id": "rec-9"}]}), captured)
    rows = ir.DuckLakeReader().named("rec_by_id", id="rec-9")
    import json as _json

    body = _json.loads(captured["body"])
    assert body == {"action": "named_read", "verb": "rec_by_id", "params": {"id": "rec-9"}}
    assert rows == [{"id": "rec-9"}]


def test_ducklake_reader_named_empty_params(monkeypatch):
    """named() with no params sends an empty params object (verbs like open_recs)."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": []}), captured)
    rows = ir.DuckLakeReader().named("open_recs")
    import json as _json

    body = _json.loads(captured["body"])
    assert body == {"action": "named_read", "verb": "open_recs", "params": {}}
    assert rows == []


def test_ducklake_reader_named_loud_fails_on_non_200(monkeypatch):
    """named() raises on a reader failure -- never a silent empty result (Decision 55)."""
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=400, text="unknown verb"), captured)
    with pytest.raises(RuntimeError, match="named_read"):
        ir.DuckLakeReader().named("not_a_verb")


class TestDuckLakeReaderSSMResolution:
    """SSM step in _reader_url() resolution chain (Decision 79 / T2.19 Slice 1)."""

    def test_ssm_url_used_when_env_unset_and_terraform_absent(self, monkeypatch) -> None:
        """env absent + terraform absent + SSM present -> URL resolved via SSM (CC-web path)."""
        import src.common.iceberg_reader as ir

        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        monkeypatch.setattr(
            ir,
            "_resolve_function_url_via_ssm",
            lambda path, profile, region: "https://ssm-resolved.lambda-url.eu-west-2.on.aws",
        )
        monkeypatch.setattr(ir, "_resolve_function_url_via_api", lambda *a, **k: None)

        url = ir.DuckLakeReader()._reader_url()
        assert url == "https://ssm-resolved.lambda-url.eu-west-2.on.aws"

    def test_ssm_called_with_correct_path(self, monkeypatch) -> None:
        """_resolve_function_url_via_ssm is called with _DUCKLAKE_READER_SSM_PATH."""
        import src.common.iceberg_reader as ir

        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))

        captured: dict = {}

        def fake_ssm(path, *, profile, region):
            captured["path"] = path
            return "https://ssm.example/"

        monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", fake_ssm)
        monkeypatch.setattr(ir, "_resolve_function_url_via_api", lambda *a, **k: None)

        ir.DuckLakeReader()._reader_url()
        assert captured["path"] == ir._DUCKLAKE_READER_SSM_PATH

    def test_ssm_skipped_when_env_set(self, monkeypatch) -> None:
        """When DUCKLAKE_READER_URL is set, SSM is never called (env takes priority)."""
        import src.common.iceberg_reader as ir

        monkeypatch.setenv("DUCKLAKE_READER_URL", "https://env-direct.example/")

        ssm_called: list[bool] = []

        def fake_ssm(*a, **k):
            ssm_called.append(True)
            return None

        monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", fake_ssm)

        url = ir.DuckLakeReader()._reader_url()
        assert url == "https://env-direct.example"
        assert not ssm_called

    def test_ssm_failure_falls_through_to_terraform(self, monkeypatch) -> None:
        """SSM returns None -> resolution continues to terraform step."""
        import src.common.iceberg_reader as ir

        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", lambda *a, **k: None)

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "https://terraform.example/"
        monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_proc)

        url = ir.DuckLakeReader()._reader_url()
        assert url == "https://terraform.example"
