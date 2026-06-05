"""Tests for src/lambdas/ducklake_writer/handler.py (T2.17, 100% coverage, mocked runtime)."""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

import src.lambdas.ducklake_writer.handler as h
from src.common import ducklake_runtime as rt

pytestmark = pytest.mark.unit


class FakeCon:
    """Connection double: records SQL; canned fetchone by substring; fetchall list."""

    def __init__(self, fetchone_map=None, fetchall_result=None):
        self.executed: list[tuple[str, object]] = []
        self.closed = False
        self._fetchone_map = fetchone_map or {}
        self._fetchall = fetchall_result or []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self):
        return self._fetchall

    def close(self):
        self.closed = True


def _result(**kw):
    base = dict(ulid="01ULID", rec_id="rec-1", occ_retries=0, commit_ms=1.0,
                created_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                last_updated_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    base.update(kw)
    return rt.WriteResult(**base)


# ---------------------------------------------------------------------------
# _parse_event / _response
# ---------------------------------------------------------------------------


def test_parse_event_body_string():
    assert h._parse_event({"body": json.dumps({"action": "write"})}) == {"action": "write"}


def test_parse_event_body_dict():
    assert h._parse_event({"body": {"action": "x"}}) == {"action": "x"}


def test_parse_event_body_empty_string():
    assert h._parse_event({"body": ""}) == {}


def test_parse_event_direct_dict():
    assert h._parse_event({"action": "y"}) == {"action": "y"}


def test_parse_event_non_dict():
    assert h._parse_event("nonsense") == {}


def test_response_envelope():
    r = h._response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["ok"] is True
    assert r["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# handler dispatch + error mapping
# ---------------------------------------------------------------------------


def test_handler_unknown_action():
    r = h.handler({"action": "nope"})
    assert r["statusCode"] == 400
    assert "unknown action" in json.loads(r["body"])["error"]


def test_handler_attach_check(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__="1.5.3"))
    r = h.handler({"action": "attach_check"})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["version"] == "1.5.3"
    assert body["source"] == "layer"
    assert con.closed is True


def test_handler_create_tables(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    called = {}
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: called.update(force=force_recreate))
    r = h.handler({"action": "create_tables", "force_recreate_tables": True})
    assert json.loads(r["body"])["force_recreate"] is True
    assert called["force"] is True


def test_handler_write(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result(ulid="01W", rec_id=rec["rec_id"]))
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    r = h.handler({"action": "write", "record": {"rec_id": "rec-9", "payload": "p"}})
    body = json.loads(r["body"])
    assert body["ulid"] == "01W"
    assert body["rec_id"] == "rec-9"


def test_handler_write_with_force_recreate(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    flags = {}
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: flags.update(f=force_recreate))
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result())
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    h.handler({"action": "write", "record": {"rec_id": "r"}, "force_recreate_tables": True})
    assert flags["f"] is True


def test_handler_idempotency_probe(monkeypatch):
    con = FakeCon(fetchone_map={"FROM ops_catalog.ducklake_smoke_history": (1,), "FROM ops_catalog.ducklake_smoke_current": (1,)})
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "mint_write_identity", lambda: rt.WriteIdentity("01ID", datetime(2026, 1, 1, tzinfo=timezone.utc)))
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result(ulid="01ID"))
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    r = h.handler({"action": "idempotency_probe"})
    body = json.loads(r["body"])
    assert body["ulid_reused"] is True
    assert body["history_rows"] == 1
    assert body["current_rows"] == 1


def test_handler_partition_probe(monkeypatch):
    con = FakeCon(fetchone_map={"ducklake_list_files('ops_catalog', 'ducklake_smoke_history')": (4,),
                                "ducklake_list_files('ops_catalog', 'ducklake_smoke_current')": (8,)})
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result())
    # _count_files returns 4/8 total; _count_files_for_predicate returns smaller via the WHERE-listing
    monkeypatch.setattr(h, "_count_files", lambda c, t: 4 if "history" in t else 8)
    monkeypatch.setattr(h, "_count_files_for_predicate", lambda c, t, p: 1)
    r = h.handler({"action": "partition_probe"})
    body = json.loads(r["body"])
    assert body["history_pruned"] is True
    assert body["history_files_scanned"] == 1
    assert body["current_partitions_scanned"] == 1


def test_handler_inlining_probe(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result())
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    monkeypatch.setattr(h, "_count_files", lambda c, t: 2)
    monkeypatch.setattr(h, "_count_inlined_rows", lambda c, t: 0)
    monkeypatch.setattr(h, "_concurrency_probe", lambda w: True)
    r = h.handler({"action": "inlining_probe"})
    body = json.loads(r["body"])
    assert body["inlined_rows"] == 0
    assert body["s3_parquet"] == 2
    assert body["occ_conflicts_handled"] is True


def test_handler_loudfail_probe(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    r = h.handler({"action": "loudfail_probe"})
    body = json.loads(r["body"])
    assert body["schema_reject"] == "raised"
    assert body["occ_exhaust"] == "raised"
    assert body["silent_drop"] is False


def test_loudfail_probe_reports_not_raised_when_gates_broken(monkeypatch):
    """Degenerate case: if the loud-fail mechanisms did NOT raise, the probe reports not_raised.

    This is the failure signal the live VP step 17 catches -- it must be observable, not masked.
    """
    con = FakeCon()
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "schema_gate", lambda rec, sem=None: None)  # broken: does not raise
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result())  # broken: does not raise
    out = h.action_loudfail_probe({}, con)
    assert out["schema_reject"] == "not_raised"
    assert out["occ_exhaust"] == "not_raised"


def test_handler_churn(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(rt, "open_connection", lambda **kw: FakeCon())
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(h, "_churn_one_writer", lambda i, dsn, creds: {"latency_ms": 10.0, "collided": False})
    r = h.handler({"action": "churn", "writers": 4})
    body = json.loads(r["body"])
    assert body["endpoint"] == "direct"
    assert body["collision_rate"] == 0.0
    assert body["within_budget"] is True


def test_handler_schema_gate_error_maps_422(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise rt.SchemaGateError("bad field")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    r = h.handler({"action": "write", "record": {"rec_id": "r"}})
    assert r["statusCode"] == 422
    assert json.loads(r["body"])["error_type"] == "schema_gate"


def test_handler_occ_exhausted_maps_503(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise rt.OCCRetryExhaustedError("exhausted")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: (lambda n, v: None))
    r = h.handler({"action": "write", "record": {"rec_id": "r"}})
    assert r["statusCode"] == 503
    assert json.loads(r["body"])["error_type"] == "occ_exhausted"


def test_handler_version_mismatch_maps_500(monkeypatch):
    def _raise():
        raise rt.VersionMismatchError("mismatch")

    monkeypatch.setattr(h, "_open_writer_connection", _raise)
    r = h.handler({"action": "attach_check"})
    assert r["statusCode"] == 500
    assert json.loads(r["body"])["error_type"] == "version_mismatch"


def test_handler_runtime_error_maps_500(monkeypatch):
    def _raise():
        raise rt.DuckLakeRuntimeError("boom")

    monkeypatch.setattr(h, "_open_writer_connection", _raise)
    r = h.handler({"action": "attach_check"})
    assert r["statusCode"] == 500
    assert json.loads(r["body"])["error_type"] == "runtime"


# ---------------------------------------------------------------------------
# metadata helpers
# ---------------------------------------------------------------------------


def test_count_files_success():
    con = FakeCon(fetchone_map={"ducklake_list_files": (3,)})
    assert h._count_files(con, rt.SMOKE_HISTORY_TABLE) == 3


def test_count_files_swallows_error():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("no such function")

    assert h._count_files(Boom(), "t") == 0


def test_count_files_for_predicate_success():
    con = FakeCon(fetchone_map={"WHERE": (1,)})
    assert h._count_files_for_predicate(con, rt.SMOKE_HISTORY_TABLE, "x = 1") == 1


def test_count_files_for_predicate_fallback():
    class PartialBoom:
        def __init__(self):
            self.calls = 0
            self._last = ""

        def execute(self, sql, params=None):
            self._last = sql
            if "ducklake_list_files" in sql:
                raise RuntimeError("no function")
            return self

        def fetchone(self):
            return (2,)

    assert h._count_files_for_predicate(PartialBoom(), "t", "x = 1") == 2


def test_count_inlined_rows_success():
    con = FakeCon(fetchone_map={"ducklake_list_inlined_data": (0,)})
    assert h._count_inlined_rows(con, rt.SMOKE_HISTORY_TABLE) == 0


def test_count_inlined_rows_swallows_error():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("nope")

    assert h._count_inlined_rows(Boom(), "t") == 0


# ---------------------------------------------------------------------------
# _AlwaysCollidingConnection / churn helpers / concurrency probe
# ---------------------------------------------------------------------------


def test_always_colliding_raises_on_merge():
    inner = FakeCon()
    wrap = h._AlwaysCollidingConnection(inner)
    with pytest.raises(RuntimeError, match="could not serialize"):
        wrap.execute("MERGE INTO x ...")


def test_always_colliding_delegates_non_merge():
    inner = FakeCon()
    wrap = h._AlwaysCollidingConnection(inner)
    wrap.execute("SELECT 1")
    wrap.execute("SELECT ? ", ["p"])
    assert any(s == "SELECT 1" for s, _ in inner.executed)


def test_churn_one_writer(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result())
    out = h._churn_one_writer(0, {"host": "h"}, ("ak", "sk", None, "r"))  # pragma: allowlist secret
    assert out["collided"] is False
    assert con.closed is True


def test_churn_one_writer_counts_occ(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)

    def _raise(c, rec, **kw):
        raise rt.OCCRetryExhaustedError("x")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    out = h._churn_one_writer(0, {"host": "h"}, ("ak", "sk", None, "r"))  # pragma: allowlist secret
    assert out["collided"] is True


def test_frozen_creds(monkeypatch):
    class _FC:
        access_key = "ak"  # pragma: allowlist secret
        secret_key = "sk"  # pragma: allowlist secret
        token = "tok"  # pragma: allowlist secret

    class _Session:
        region_name = "eu-west-2"

        def get_credentials(self):
            return types.SimpleNamespace(get_frozen_credentials=lambda: _FC())

    import boto3

    monkeypatch.setattr(boto3, "Session", lambda: _Session())
    ak, sk, tok, region = h._frozen_creds()
    assert ak == "ak" and region == "eu-west-2"


def test_p95():
    assert h._p95([]) == 0.0
    assert h._p95([10.0, 20.0, 30.0, 40.0]) == 40.0


def test_concurrency_probe_success(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "r"))  # pragma: allowlist secret
    monkeypatch.setattr(h, "_churn_one_writer", lambda i, d, c: {"latency_ms": 1.0, "collided": False})
    assert h._concurrency_probe(2) is True


def test_concurrency_probe_runtime_error_is_handled(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "r"))  # pragma: allowlist secret

    def _raise(i, d, c):
        raise rt.OCCRetryExhaustedError("x")

    monkeypatch.setattr(h, "_churn_one_writer", _raise)
    assert h._concurrency_probe(2) is True


def test_concurrency_probe_hard_error_false(monkeypatch):
    def _raise():
        raise RuntimeError("dsn fail")

    monkeypatch.setattr(rt, "fetch_dsn", _raise)
    assert h._concurrency_probe(2) is False


# ---------------------------------------------------------------------------
# _open_writer_connection
# ---------------------------------------------------------------------------


def test_open_writer_connection(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    captured = {}
    monkeypatch.setattr(rt, "open_connection", lambda **kw: captured.update(kw) or "CON")
    out = h._open_writer_connection()
    assert out == "CON"
    assert captured["extension_directory"] == h.EXTENSION_DIRECTORY
