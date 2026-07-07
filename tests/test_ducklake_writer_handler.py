"""Tests for src/lambdas/ducklake_writer/handler.py (T2.17, 100% coverage, mocked runtime)."""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

import src.lambdas.ducklake_writer.handler as h
from src.common import ducklake_runtime as rt
from src.common.ducklake_version import pinned_duckdb_version

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


@pytest.fixture(autouse=True)
def _reset_warm_connection():
    """The writer uses a per-container warm-connection global on the single-statement path (D2);
    reset it around every test so a cached connection never leaks between tests."""
    rt.reset_warm_connection()
    yield
    rt.reset_warm_connection()


def _result(**kw):
    base = dict(
        ulid="01ULID",
        rec_id="rec-1",
        occ_retries=0,
        commit_ms=1.0,
        created_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_updated_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
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
    monkeypatch.setattr(
        rt.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__=pinned_duckdb_version())
    )
    r = h.handler({"action": "attach_check"})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["version"] == pinned_duckdb_version()
    assert body["source"] == "layer"
    # D2 warm reuse: the single-statement path keeps the connection open for the next invocation.
    assert con.closed is False
    assert body["connect_reused"] is False  # first (cold) acquisition in this container


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
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
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
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    h.handler({"action": "write", "record": {"rec_id": "r"}, "force_recreate_tables": True})
    assert flags["f"] is True


def test_handler_idempotency_probe(monkeypatch):
    con = FakeCon(
        fetchone_map={"FROM ops_catalog.ducklake_smoke_history": (1,), "FROM ops_catalog.ducklake_smoke_current": (1,)}
    )
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "mint_write_identity", lambda: rt.WriteIdentity("01ID", datetime(2026, 1, 1, tzinfo=timezone.utc)))
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result(ulid="01ID"))
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    r = h.handler({"action": "idempotency_probe"})
    body = json.loads(r["body"])
    assert body["ulid_reused"] is True
    assert body["history_rows"] == 1
    assert body["current_rows"] == 1


def test_handler_partition_probe(monkeypatch):
    con = FakeCon(
        fetchone_map={
            "ducklake_list_files('ops_catalog', 'ducklake_smoke_history')": (4,),
            "ducklake_list_files('ops_catalog', 'ducklake_smoke_current')": (8,),
        }
    )
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
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
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


def _churn_result(**kw) -> dict:
    """Default mock return value for _churn_one_writer (all attribution fields)."""
    base = {
        "latency_ms": 10.0,
        "collided": False,
        "connect_ms": 3.0,
        "commit_ms": 5.0,
        "occ_retries": 0,
        "wall_ms": 10.0,
        "cpu_ms": 8.0,
    }
    base.update(kw)
    return base


def test_handler_churn(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(rt, "open_connection", lambda **kw: FakeCon())
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    monkeypatch.setattr(h, "_churn_one_writer", lambda i, dsn, creds: _churn_result())
    r = h.handler({"action": "churn", "writers": 4})
    body = json.loads(r["body"])
    assert body["endpoint"] == "direct"
    assert body["collision_rate"] == 0.0
    assert body["within_budget"] is True
    assert "breakdown" in body
    bd = body["breakdown"]
    assert bd["writers"] == 4
    assert bd["total_occ_retries"] == 0
    assert "p95_connect_ms" in bd
    assert "p95_cpu_ms" in bd
    assert "wall_cpu_ratio" in bd
    # rec-2096: cold AND warm connect latency are recorded so a cold-connect regression is visible.
    assert "cold_connect_ms" in bd
    assert "warm_connect_ms" in bd


def test_handler_churn_single_normal(monkeypatch):
    """action_churn_single (normal, no setup) calls _churn_one_single_write and returns attribution."""
    seen_ids: list[int] = []
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(h, "_churn_one_single_write", lambda i, dsn, creds: seen_ids.append(i) or _churn_result())
    r = h.handler({"action": "churn_single", "writer_id": 3})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["ok"] is True
    assert seen_ids == [3]
    assert "latency_ms" in body
    assert "collided" in body
    assert "connect_ms" in body
    assert "commit_ms" in body
    assert "cpu_ms" in body
    assert "occ_retries" in body


def test_churn_one_single_write(monkeypatch):
    """_churn_one_single_write opens a connection, writes ONCE, and returns attribution dict."""
    con = FakeCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: _result(commit_ms=200.0, occ_retries=0))
    out = h._churn_one_single_write(5, {"host": "h"}, ("ak", "sk", None, "r"))  # pragma: allowlist secret
    assert out["collided"] is False
    assert con.closed is True
    assert out["commit_ms"] == 200.0
    assert out["occ_retries"] == 0
    assert "connect_ms" in out
    assert "wall_ms" in out
    assert "cpu_ms" in out


def test_churn_one_single_write_occ(monkeypatch):
    """_churn_one_single_write marks collided=True when OCCRetryExhaustedError is raised."""
    con = FakeCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)
    monkeypatch.setattr(rt, "write_scd2", lambda c, rec, **kw: (_ for _ in ()).throw(rt.OCCRetryExhaustedError("x")))
    out = h._churn_one_single_write(0, {"host": "h"}, ("ak", "sk", None, "r"))  # pragma: allowlist secret
    assert out["collided"] is True
    assert con.closed is True


def test_handler_churn_single_setup(monkeypatch):
    """action_churn_single with setup=True pre-creates tables and returns {"ok":true,"setup":true}."""
    con = FakeCon()
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(h, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)
    create_calls: list[bool] = []
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: create_calls.append(force_recreate))
    r = h.handler({"action": "churn_single", "setup": True})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["ok"] is True
    assert body["setup"] is True
    assert create_calls == [True]
    assert con.closed is True


def test_handler_schema_gate_error_maps_422(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise rt.SchemaGateError("bad field")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    r = h.handler({"action": "write", "record": {"rec_id": "r"}})
    assert r["statusCode"] == 422
    assert json.loads(r["body"])["error_type"] == "schema_gate"


def test_handler_occ_exhausted_maps_503(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise rt.OCCRetryExhaustedError("exhausted")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
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


def test_handler_status_transition_error_maps_422(monkeypatch):
    """A resolved-rec reactivation (StatusTransitionError) maps to 422 error_type=status_transition."""
    con = FakeCon()
    monkeypatch.setattr(h, "_open_writer_connection", lambda: con)

    def _raise(c, rec, **kw):
        raise rt.StatusTransitionError("illegal status transition 'closed' -> 'open'")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    r = h.handler({"action": "update_ops", "table": "ops_recommendations", "record": {"id": "rec-1", "status": "open"}})
    assert r["statusCode"] == 422
    assert json.loads(r["body"])["error_type"] == "status_transition"


# ---------------------------------------------------------------------------
# describe: per-verb parameter schema (CD.10 / CD.15), connectionless
# ---------------------------------------------------------------------------


def test_action_describe_returns_write_verb_schema():
    out = h.action_describe({}, None)
    assert out["ok"] is True
    assert set(out["verbs"]) == set(rt.VERB_REGISTRY)
    assert "params_schema" in out["verbs"]["update_ops"]


def test_describe_in_connectionless_actions():
    assert "describe" in h._CONNECTIONLESS_ACTIONS
    assert h._ACTIONS["describe"] is h.action_describe


def test_handler_describe_end_to_end():
    r = h.handler({"action": "describe"})
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["ok"] is True
    assert "write_ops" in body["verbs"]


# ---------------------------------------------------------------------------
# Growth-safe per-verb parametrized dispatch: every VERB_REGISTRY write verb has a describe entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(rt.VERB_REGISTRY))
def test_describe_write_verbs_covers_every_registered_verb(verb):
    out = h.action_describe({}, None)
    assert verb in out["verbs"]
    assert "description" in out["verbs"][verb]
    assert "params_schema" in out["verbs"][verb]


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
    assert "connect_ms" in out
    assert "commit_ms" in out
    assert "wall_ms" in out
    assert "cpu_ms" in out
    assert out["occ_retries"] == 0
    assert out["commit_ms"] == round(_result().commit_ms * rt.CHURN_WRITES_PER_WRITER, 2)


def test_churn_one_writer_counts_occ(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)

    def _raise(c, rec, **kw):
        raise rt.OCCRetryExhaustedError("x")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    out = h._churn_one_writer(0, {"host": "h"}, ("ak", "sk", None, "r"))  # pragma: allowlist secret
    assert out["collided"] is True
    assert out["commit_ms"] == 0.0
    assert out["occ_retries"] == 0
    assert "wall_ms" in out
    assert "cpu_ms" in out


def test_churn_constants_imported_from_runtime():
    assert rt.COMMIT_LATENCY_BUDGET_MS == 2000.0
    assert rt.OCC_COLLISION_RATE_BUDGET == 0.20
    assert rt.CHURN_WRITERS == 4  # Decision 82: N steered 8->4; budget VALUES (above) unchanged
    assert rt.CHURN_WRITES_PER_WRITER == 5
    assert not hasattr(h, "COMMIT_LATENCY_BUDGET_MS")
    assert not hasattr(h, "OCC_COLLISION_RATE_BUDGET")
    assert not hasattr(h, "CHURN_WRITERS")
    assert not hasattr(h, "CHURN_WRITES_PER_WRITER")


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


# ---------------------------------------------------------------------------
# T2.19 production ops actions: write_ops / update_ops / create_ops_tables
# ---------------------------------------------------------------------------


def test_action_write_ops_dispatches_to_runtime(monkeypatch):
    captured = {}

    def _write(con, record, *, table, **kw):  # noqa: ARG001
        captured["table"] = table
        captured["record"] = record
        return _result(ulid="01W", rec_id="rec-9")

    monkeypatch.setattr(rt, "write_scd2", _write)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    out = h.action_write_ops({"table": "ops_recommendations", "record": {"id": "rec-9", "status": "open"}}, FakeCon())
    assert out["ok"] is True
    assert out["table"] == "ops_recommendations"
    assert out["key"] == "rec-9"
    assert captured["table"] == "ops_recommendations"


def test_action_update_ops_sets_require_exists(monkeypatch):
    captured = {}

    def _write(con, record, *, table, require_exists=False, **kw):  # noqa: ARG001
        captured["require_exists"] = require_exists
        return _result(rec_id=record["id"])

    monkeypatch.setattr(rt, "write_scd2", _write)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    out = h.action_update_ops({"table": "ops_recommendations", "record": {"id": "rec-1", "status": "closed"}}, FakeCon())
    assert out["ok"] is True
    assert captured["require_exists"] is True


def test_action_create_ops_tables(monkeypatch):
    calls = {}

    def _create(con, *, table, force_recreate):  # noqa: ARG001
        calls.update(table=table, force=force_recreate)

    monkeypatch.setattr(rt, "create_scd2_tables", _create)
    out = h.action_create_ops_tables(
        {"table": "ops_decisions", "force_recreate_tables": True, "confirm_force_recreate": "ops_decisions"},
        FakeCon(),
    )
    assert out["ok"] is True
    assert calls == {"table": "ops_decisions", "force": True}
    assert out["tables"] == ["ops_decisions_history", "ops_decisions_current"]


def test_action_create_ops_tables_force_requires_confirm(monkeypatch):
    """Destructive-action guard (Decision 84): force_recreate without confirm loud-fails."""
    monkeypatch.setattr(rt, "create_scd2_tables", lambda con, *, table, force_recreate: None)
    with pytest.raises(h.WriterActionError, match="confirm_force_recreate"):
        h.action_create_ops_tables({"table": "ops_decisions", "force_recreate_tables": True}, FakeCon())


def test_action_create_ops_tables_plain_create_needs_no_confirm(monkeypatch):
    calls = {}

    def _create(con, *, table, force_recreate):  # noqa: ARG001
        calls.update(table=table, force=force_recreate)

    monkeypatch.setattr(rt, "create_scd2_tables", _create)
    out = h.action_create_ops_tables({"table": "ops_priority_queue"}, FakeCon())
    assert out["ok"] is True
    assert calls == {"table": "ops_priority_queue", "force": False}


def test_action_file_ops(monkeypatch):
    captured = {}

    def _file(con, record, *, table, identity, metric_sink):  # noqa: ARG001
        captured.update(record=dict(record), table=table, identity=identity)
        from datetime import datetime, timezone

        from src.common.ducklake_scd2_schema import WriteResult

        ts = datetime(2026, 6, 11, tzinfo=timezone.utc)
        return WriteResult(
            ulid=identity.ulid if identity else "01AUTO",
            rec_id="rec-2171",
            occ_retries=0,
            commit_ms=12.0,
            created_timestamp=ts,
            last_updated_timestamp=ts,
        )

    monkeypatch.setattr(rt, "file_scd2", _file)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    out = h.action_file_ops(
        {
            "table": "ops_recommendations",
            "record": {"title": "t", "status": "open"},
            "idempotency_ulid": "01JXQ4N9V8TEST0000000000",
        },
        FakeCon(),
    )
    assert out["ok"] is True
    assert out["key"] == "rec-2171"
    assert captured["table"] == "ops_recommendations"
    assert captured["identity"].ulid == "01JXQ4N9V8TEST0000000000"


def test_action_file_ops_rejects_bad_idempotency_ulid(monkeypatch):
    monkeypatch.setattr(rt, "file_scd2", lambda *a, **k: None)
    with pytest.raises(h.WriterActionError, match="idempotency_ulid"):
        h.action_file_ops({"table": "ops_recommendations", "record": {}, "idempotency_ulid": "no spaces!"}, FakeCon())


def test_action_file_ops_without_idempotency_mints_identity(monkeypatch):
    captured = {}

    def _file(con, record, *, table, identity, metric_sink):  # noqa: ARG001
        captured["identity"] = identity
        from datetime import datetime, timezone

        from src.common.ducklake_scd2_schema import WriteResult

        ts = datetime(2026, 6, 11, tzinfo=timezone.utc)
        return WriteResult("01X", "rec-1", 0, 1.0, ts, ts)

    monkeypatch.setattr(rt, "file_scd2", _file)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    out = h.action_file_ops({"table": "ops_recommendations", "record": {"title": "t"}}, FakeCon())
    assert out["ok"] is True
    assert captured["identity"] is None


def test_require_ops_table_rejects_unknown():
    with pytest.raises(h.WriterActionError, match="unknown or missing ops table"):
        h._require_ops_table("not_a_table")


def test_require_ops_table_rejects_non_string():
    with pytest.raises(h.WriterActionError):
        h._require_ops_table(None)


def test_handler_write_ops_unknown_table_returns_400(monkeypatch):
    monkeypatch.setattr(h, "_open_writer_connection", lambda: FakeCon())
    resp = h.handler({"action": "write_ops", "table": "bogus", "record": {}})
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_type"] == "action"


def test_handler_update_ops_referential_returns_409(monkeypatch):
    monkeypatch.setattr(h, "_open_writer_connection", lambda: FakeCon())

    def _raise(*a, **k):
        raise rt.ReferentialError("absent rec-x")

    monkeypatch.setattr(rt, "write_scd2", _raise)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    resp = h.handler({"action": "update_ops", "table": "ops_recommendations", "record": {"id": "rec-x", "status": "closed"}})
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error_type"] == "referential"


# ---------------------------------------------------------------------------
# connect_probe: runs WITHOUT a pre-opened connection
# ---------------------------------------------------------------------------


def test_handler_reopens_on_dead_connection_and_retries(monkeypatch):
    """A dead-session error on the single-statement write path reopens ONCE and retries (D2).

    Production write actions are replay-safe under retry (file_ops via the client ULID; update/write_ops
    MERGE-idempotent), and a connection death aborts the catalog txn, so the retry commits exactly once.
    """
    opens: list[int] = []
    monkeypatch.setattr(h, "_open_writer_connection", lambda: opens.append(1) or FakeCon())
    calls = {"n": 0}

    def flaky_write_scd2(con, rec, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("could not connect to server: connection refused")  # dead session
        return _result()

    monkeypatch.setattr(rt, "write_scd2", flaky_write_scd2)
    r = h.handler({"action": "write_ops", "table": "ops_recommendations", "record": {"id": "rec-1"}})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["ok"] is True
    assert len(opens) == 2  # cold open + one reopen


def test_handler_reset_warm_connection(monkeypatch):
    """reset_warm_connection is connectionless: it drops the warm cache without opening a connection (D2 VP)."""

    def _should_not_open():
        raise AssertionError("reset_warm_connection must not open a connection")

    monkeypatch.setattr(h, "_open_writer_connection", _should_not_open)
    reset_called = {"n": 0}
    monkeypatch.setattr(rt, "reset_warm_connection", lambda: reset_called.__setitem__("n", reset_called["n"] + 1))
    r = h.handler({"action": "reset_warm_connection"})
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body == {"ok": True, "reset": True}
    assert reset_called["n"] == 1


def test_handler_connect_probe_runs_without_connection(monkeypatch):
    """connect_probe action returns the structured probe result even when _open_writer_connection would hang.

    Proves the probe is dispatched via _CONNECTIONLESS_ACTIONS ahead of _open_writer_connection.
    """
    hang_called = {"called": False}

    def _hanging_open():
        hang_called["called"] = True
        raise RuntimeError("hang: should not be called for connect_probe")

    monkeypatch.setattr(h, "_open_writer_connection", _hanging_open)
    fake_result = {
        "phase_reached": "tcp",
        "failed_phase": "auth",
        "dns_ms": 5.0,
        "tcp_ms": 8.0,
        "auth_ms": 12.0,
        "attach_ms": None,
        "ok": False,
        "error": "AUTH: authentication failed",
    }
    import src.common.ducklake_connect_probe as p

    monkeypatch.setattr(p, "probe_connection", lambda dsn, **kw: fake_result)
    _fake_dsn = {"host": "h", "dbname": "d", "username": "u", "password": "p"}  # pragma: allowlist secret
    monkeypatch.setattr(rt, "fetch_dsn", lambda: _fake_dsn)

    r = h.handler({"action": "connect_probe"})
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["failed_phase"] == "auth"
    assert body["ok"] is False
    assert hang_called["called"] is False, "_open_writer_connection must NOT be called for connect_probe"


def test_handler_connect_probe_success(monkeypatch):
    """connect_probe returns ok=True and phase_reached=attach on a successful probe."""
    monkeypatch.setattr(h, "_open_writer_connection", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))
    success_result = {
        "phase_reached": "attach",
        "failed_phase": None,
        "dns_ms": 2.0,
        "tcp_ms": 5.0,
        "auth_ms": 50.0,
        "attach_ms": 1200.0,
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
    """connect_probe must be in _CONNECTIONLESS_ACTIONS so it bypasses _open_writer_connection."""
    assert "connect_probe" in h._CONNECTIONLESS_ACTIONS


def test_action_create_ops_tables_caller_keyspace_skips_counter(monkeypatch):
    """ops_decisions has a caller-owned keyspace (DECISIONS.md numbering): no counter is seeded."""
    monkeypatch.setattr(rt, "create_scd2_tables", lambda con, *, table, force_recreate: None)
    called = []
    monkeypatch.setattr(rt, "bootstrap_entity_counter", lambda con, spec: called.append(spec.table))
    out = h.action_create_ops_tables({"table": "ops_decisions"}, FakeCon())
    assert out["ok"] is True
    assert out["counter_seed"] is None
    assert called == []


def test_action_file_ops_rejects_caller_keyspace_table(monkeypatch):
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    with pytest.raises(rt.DuckLakeRuntimeError, match="no writer-owned keyspace"):
        h.action_file_ops({"table": "ops_decisions", "record": {"title": "t", "status": "open"}}, FakeCon())


def test_action_write_ops_append_only_table(monkeypatch):
    """write_ops on ops_smoke_events (append_only) routes through write_scd2 without error."""
    captured = {}

    def _write(con, record, *, table, **kw):  # noqa: ARG001
        captured["table"] = table
        captured["record"] = record
        return _result(ulid="01AO", rec_id="test-ao-event-1")

    monkeypatch.setattr(rt, "write_scd2", _write)
    monkeypatch.setattr(rt, "make_metric_sink", lambda: None)
    out = h.action_write_ops(
        {"table": "ops_smoke_events", "record": {"event_id": "test-ao-event-1", "event_type": "smoke"}},
        FakeCon(),
    )
    assert out["ok"] is True
    assert out["table"] == "ops_smoke_events"
    assert captured["table"] == "ops_smoke_events"
