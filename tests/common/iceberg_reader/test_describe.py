"""Tests for DuckLakeReader.describe() (src/common/iceberg_reader.py).

Split alongside test_ducklake_reader.py within the tests/common/iceberg_reader/ concern-split
package (rec-2709 Wave 11 convention). Deliberately no module-level boto3/requests import: its
sibling test_ducklake_reader.py is the declared HEAVY-DEP MARKER MODULE for this package, so this
module stays fast-tier collectible.
"""

from __future__ import annotations

import json as _json

import pytest

from src.common.iceberg_reader import ReaderInvokeError


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text if text else _json.dumps(self._payload)

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


def test_describe_returns_verb_map(monkeypatch):
    """describe() unwraps body["verbs"] rather than handing back the raw {"ok", "verbs"} envelope."""
    verbs_payload = {
        "rec_by_id": {
            "table": "ops_recommendations",
            "description": "Single recommendation by id.",
            "params": ["id"],
            "paginable": False,
            "params_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        }
    }
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"ok": True, "verbs": verbs_payload}), captured)
    verbs = ir.DuckLakeReader().describe()
    assert verbs == verbs_payload
    body = _json.loads(captured["body"])
    assert body == {"action": "describe"}


def test_describe_empty_verbs_returns_empty_dict(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"ok": True, "verbs": {}}), captured)
    assert ir.DuckLakeReader().describe() == {}


def test_describe_loud_fails_on_non_200(monkeypatch):
    """describe() never falls back to a hardcoded verb list -- a boundary failure raises (Decision 55)."""
    captured: dict = {}
    error_body = '{"ok": false, "error_type": "runtime", "error": "boom"}'
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=500, text=error_body), captured)
    with pytest.raises(ReaderInvokeError, match="describe"):
        ir.DuckLakeReader().describe()


def test_describe_reuses_invoke_not_a_second_transport(monkeypatch):
    """describe() issues its request through the same _invoke seam as named()/query() -- no parallel client."""
    captured: dict = {}
    calls: list = []
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"ok": True, "verbs": {}}), captured)

    reader = ir.DuckLakeReader()
    real_invoke = reader._invoke

    def _spy_invoke(payload):
        calls.append(payload)
        return real_invoke(payload)

    reader._invoke = _spy_invoke
    reader.describe()
    assert calls == [{"action": "describe"}]


def test_reader_invoke_error_carries_status_and_parsed_body(monkeypatch):
    """A non-200 response's HTTP status and parsed JSON body survive on the raised exception."""
    captured: dict = {}
    body = {"ok": False, "error_type": "version_mismatch", "error": "schema drift"}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=500, text=_json.dumps(body)), captured)
    with pytest.raises(ReaderInvokeError) as exc_info:
        ir.DuckLakeReader().describe()
    err = exc_info.value
    assert err.status == 500
    assert err.body == body
    assert err.action == "describe"


def test_reader_invoke_error_body_none_on_non_json_text(monkeypatch):
    """A non-JSON error body parses to None rather than raising a secondary decode error.

    Uses a non-transient status (501): a transient status (502/503/504) would trigger _invoke's
    real retry-with-sleep loop against this single-canned-response mock.
    """
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=501, text="<html>not implemented</html>"), captured)
    with pytest.raises(ReaderInvokeError) as exc_info:
        ir.DuckLakeReader().named("open_recs")
    assert exc_info.value.body is None


def test_reader_invoke_error_is_a_runtime_error(monkeypatch):
    """ReaderInvokeError subclasses RuntimeError -- the repo-wide `except RuntimeError` reader site
    (scripts/verifiers/athena_views.py) must not regress."""
    from src.common.iceberg_reader import ReaderInvokeError as RIE

    assert issubclass(RIE, RuntimeError)
