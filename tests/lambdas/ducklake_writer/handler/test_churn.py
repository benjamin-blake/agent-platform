"""Churn / concurrency-probe / colliding-connection concern for
src/lambdas/ducklake_writer/handler.py (T2.17, 100% coverage, mocked runtime).

Split from the former tests/test_ducklake_writer_handler.py monolith (rec-2709 Wave 8).
Functions copied VERBATIM; _churn_result stays LOCAL to this module.

HEAVY-DEP MARKER MODULE: test_frozen_creds does a lazy `import boto3` inside its body. The
fast CI tier runs with requirements-fast.txt, which excludes boto3 -- the module-level
`import boto3` marker below proactively defers this module's collection to the full tier
(convergence_health precedent, tests/CLAUDE.md heavy-dep marker directive).
"""

from __future__ import annotations

import json
import types

import boto3  # noqa: F401 -- heavy-dep marker: defers this module to the full CI tier (test_frozen_creds)
import pytest

import src.lambdas.ducklake_writer.handler as h
from src.common import ducklake_runtime as rt
from src.lambdas.ducklake_writer import smoke_actions
from tests.fixtures.ducklake_writer_handler import FakeCon, _result

pytestmark = pytest.mark.unit


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
    monkeypatch.setattr(smoke_actions, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(rt, "open_connection", lambda **kw: FakeCon())
    monkeypatch.setattr(rt, "create_scd2_tables", lambda c, force_recreate=False: None)
    monkeypatch.setattr(rt, "make_metric_sink", lambda **kw: lambda n, v: None)
    monkeypatch.setattr(smoke_actions, "_churn_one_writer", lambda i, dsn, creds: _churn_result())
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
    monkeypatch.setattr(smoke_actions, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
    monkeypatch.setattr(smoke_actions, "_churn_one_single_write", lambda i, dsn, creds: seen_ids.append(i) or _churn_result())
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
    monkeypatch.setattr(smoke_actions, "_frozen_creds", lambda: ("ak", "sk", None, "eu-west-2"))  # pragma: allowlist secret
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

    import boto3  # noqa: F811 -- verbatim lazy in-test import, redundant with the module-level marker above

    monkeypatch.setattr(boto3, "Session", lambda: _Session())
    ak, sk, tok, region = h._frozen_creds()
    assert ak == "ak" and region == "eu-west-2"


def test_p95():
    assert h._p95([]) == 0.0
    assert h._p95([10.0, 20.0, 30.0, 40.0]) == 40.0


def test_concurrency_probe_success(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(smoke_actions, "_frozen_creds", lambda: ("ak", "sk", None, "r"))  # pragma: allowlist secret
    monkeypatch.setattr(smoke_actions, "_churn_one_writer", lambda i, d, c: {"latency_ms": 1.0, "collided": False})
    assert h._concurrency_probe(2) is True


def test_concurrency_probe_runtime_error_is_handled(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    monkeypatch.setattr(smoke_actions, "_frozen_creds", lambda: ("ak", "sk", None, "r"))  # pragma: allowlist secret

    def _raise(i, d, c):
        raise rt.OCCRetryExhaustedError("x")

    monkeypatch.setattr(smoke_actions, "_churn_one_writer", _raise)
    assert h._concurrency_probe(2) is True


def test_concurrency_probe_hard_error_false(monkeypatch):
    def _raise():
        raise RuntimeError("dsn fail")

    monkeypatch.setattr(rt, "fetch_dsn", _raise)
    assert h._concurrency_probe(2) is False
