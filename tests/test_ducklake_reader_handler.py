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
    rows = [
        {
            "ulid": "01A",
            "rec_id": "rec-1",
            "payload": "p",
            "created_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_updated_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
    ]
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


def test_handler_write_probe_denied(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_reader_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise RuntimeError("AccessDenied: s3:PutObject")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    r = h.handler({"action": "write_probe"})
    body = json.loads(r["body"])
    assert body["write_denied"] is True
    assert body["detail"] == "RuntimeError"


def test_handler_write_probe_boundary_broken(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_reader_connection", lambda: con)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: None)  # write SUCCEEDS (boundary broken)
    r = h.handler({"action": "write_probe"})
    assert json.loads(r["body"])["write_denied"] is False


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


# ---------------------------------------------------------------------------
# T2.19 production ops read actions: read_ops_current / read_ops_history / query_ops
# ---------------------------------------------------------------------------


def test_action_read_ops_current(monkeypatch):
    rows = [{"id": "rec-1", "status": "open", "created_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)}]
    monkeypatch.setattr(rt, "read_current", lambda con, *, table, key, limit: rows)
    out = h.action_read_ops_current({"table": "ops_recommendations", "id": "rec-1"}, FakeCon())
    assert out["ok"] is True
    assert out["row_count"] == 1
    # datetime is coerced to ISO string for the JSON body
    assert isinstance(out["rows"][0]["created_timestamp"], str)


def test_action_read_ops_history(monkeypatch):
    monkeypatch.setattr(rt, "read_history", lambda con, *, table, key, limit: [{"ulid": "01A"}, {"ulid": "01B"}])
    out = h.action_read_ops_history({"table": "ops_decisions", "limit": 5}, FakeCon())
    assert out["row_count"] == 2


def test_action_query_ops(monkeypatch):
    monkeypatch.setattr(rt, "query_current", lambda con, *, table, sql, params: [{"violation": 0}])
    out = h.action_query_ops({"table": "ops_recommendations", "sql": "SELECT 1 FROM {tbl}"}, FakeCon())
    assert out["row_count"] == 1


def test_action_query_ops_requires_sql():
    with pytest.raises(rt.DuckLakeRuntimeError, match="non-empty 'sql'"):
        h.action_query_ops({"table": "ops_recommendations"}, FakeCon())


def test_require_ops_table_rejects_unknown():
    with pytest.raises(rt.DuckLakeRuntimeError, match="unknown or missing ops table"):
        h._require_ops_table("nope")


def test_handler_read_ops_current_end_to_end(monkeypatch):
    monkeypatch.setattr(h, "_open_reader_connection", lambda: FakeCon())
    monkeypatch.setattr(rt, "read_current", lambda con, *, table, key, limit: [{"id": "rec-1"}])
    resp = h.handler({"action": "read_ops_current", "table": "ops_recommendations"})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["row_count"] == 1


# ---------------------------------------------------------------------------
# connect_probe: runs WITHOUT a pre-opened connection
# ---------------------------------------------------------------------------


def test_handler_connect_probe_runs_without_connection(monkeypatch):
    """connect_probe action returns the structured probe result even when _open_reader_connection would hang.

    Proves the probe is dispatched via _CONNECTIONLESS_ACTIONS ahead of _open_reader_connection.
    """
    hang_called = {"called": False}

    def _hanging_open():
        hang_called["called"] = True
        raise RuntimeError("hang: should not be called for connect_probe")

    monkeypatch.setattr(h, "_open_reader_connection", _hanging_open)
    fake_result = {
        "phase_reached": "dns",
        "failed_phase": "tcp",
        "dns_ms": 4.0,
        "tcp_ms": 10001.0,
        "auth_ms": None,
        "attach_ms": None,
        "ok": False,
        "error": "TCP: timed out",
    }
    import src.common.ducklake_connect_probe as p

    monkeypatch.setattr(p, "probe_connection", lambda dsn, **kw: fake_result)
    _fake_dsn = {"host": "h", "dbname": "d", "username": "u", "password": "p"}  # pragma: allowlist secret
    monkeypatch.setattr(rt, "fetch_dsn", lambda: _fake_dsn)

    r = h.handler({"action": "connect_probe"})
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["failed_phase"] == "tcp"
    assert body["ok"] is False
    assert hang_called["called"] is False, "_open_reader_connection must NOT be called for connect_probe"


def test_handler_connect_probe_success(monkeypatch):
    """connect_probe returns ok=True and phase_reached=attach on a successful probe."""
    monkeypatch.setattr(h, "_open_reader_connection", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))
    success_result = {
        "phase_reached": "attach",
        "failed_phase": None,
        "dns_ms": 1.5,
        "tcp_ms": 4.0,
        "auth_ms": 45.0,
        "attach_ms": 900.0,
        "ok": True,
        "error": None,
    }
    import src.common.ducklake_connect_probe as p

    monkeypatch.setattr(p, "probe_connection", lambda dsn, **kw: success_result)
    _fake_dsn = {"host": "h", "dbname": "d", "username": "u", "password": "p"}  # pragma: allowlist secret
    monkeypatch.setattr(rt, "fetch_dsn", lambda: _fake_dsn)

    r = h.handler({"action": "connect_probe"})
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["ok"] is True
    assert body["phase_reached"] == "attach"
    assert body["failed_phase"] is None


def test_connect_probe_in_connectionless_actions():
    """connect_probe must be in _CONNECTIONLESS_ACTIONS so it bypasses _open_reader_connection."""
    assert "connect_probe" in h._CONNECTIONLESS_ACTIONS
