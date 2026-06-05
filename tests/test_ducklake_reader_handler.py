"""Tests for src/lambdas/ducklake_reader/handler.py (T2.17, 100% coverage, mocked runtime)."""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

import src.lambdas.ducklake_reader.handler as h
from src.common import ducklake_runtime as rt

pytestmark = pytest.mark.unit


class FakeCon:
    def __init__(self):
        self.executed: list[tuple[str, object]] = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# _parse_event / _response
# ---------------------------------------------------------------------------


def test_parse_event_variants():
    assert h._parse_event({"body": json.dumps({"action": "read_current"})}) == {"action": "read_current"}
    assert h._parse_event({"body": {"action": "x"}}) == {"action": "x"}
    assert h._parse_event({"body": ""}) == {}
    assert h._parse_event({"action": "y"}) == {"action": "y"}
    assert h._parse_event(123) == {}


def test_response_envelope():
    r = h._response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["ok"] is True


# ---------------------------------------------------------------------------
# _json_safe
# ---------------------------------------------------------------------------


def test_json_safe_coerces_datetimes():
    rows = [{"ulid": "01A", "created_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "payload": "p"}]
    out = h._json_safe(rows)
    assert out[0]["created_timestamp"] == "2026-01-01T00:00:00+00:00"
    assert out[0]["payload"] == "p"


# ---------------------------------------------------------------------------
# handler dispatch
# ---------------------------------------------------------------------------


def test_handler_unknown_action():
    r = h.handler({"action": "nope"})
    assert r["statusCode"] == 400


def test_handler_attach_check(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_reader_connection", lambda: con)
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__="1.5.3"))
    r = h.handler({"action": "attach_check"})
    body = json.loads(r["body"])
    assert body["version"] == "1.5.3"
    assert body["source"] == "layer"
    assert con.closed is True


def test_handler_read_current(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_reader_connection", lambda: con)
    rows = [{"ulid": "01A", "rec_id": "rec-1", "payload": "p",
             "created_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
             "last_updated_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)}]
    monkeypatch.setattr(rt, "read_current", lambda c, rec_id=None, limit=None: rows)
    r = h.handler({"action": "read_current", "rec_id": "rec-1", "limit": 10})
    body = json.loads(r["body"])
    assert body["row_count"] == 1
    assert body["rows"][0]["rec_id"] == "rec-1"


def test_handler_partition_prune_check(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_reader_connection", lambda: con)
    monkeypatch.setattr(rt, "read_current", lambda c, rec_id=None, limit=None: [{"rec_id": rec_id}])
    r = h.handler({"action": "partition_prune_check", "rec_id": "rec-part-0"})
    body = json.loads(r["body"])
    assert body["rows_returned"] == 1
    assert body["partitions_scanned"] == 1


def test_handler_version_mismatch_maps_500(monkeypatch):
    def _raise():
        raise rt.VersionMismatchError("mismatch")

    monkeypatch.setattr(h, "_open_reader_connection", _raise)
    r = h.handler({"action": "attach_check"})
    assert r["statusCode"] == 500
    assert json.loads(r["body"])["error_type"] == "version_mismatch"


def test_handler_runtime_error_maps_500(monkeypatch):
    def _raise():
        raise rt.DuckLakeRuntimeError("boom")

    monkeypatch.setattr(h, "_open_reader_connection", _raise)
    r = h.handler({"action": "read_current"})
    assert r["statusCode"] == 500
    assert json.loads(r["body"])["error_type"] == "runtime"


def test_open_reader_connection(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    captured = {}
    monkeypatch.setattr(rt, "open_connection", lambda **kw: captured.update(kw) or "CON")
    out = h._open_reader_connection()
    assert out == "CON"
    assert captured["extension_directory"] == h.EXTENSION_DIRECTORY
