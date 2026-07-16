"""CONCERN: scripts/ducklake_smoke/lambda_ec_gates.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: lambda_attach/ingress/
idempotency/partition/inlining/loudfail (with the _patch_gate helper), the lambda_churn fan-out
cohort (with _churn_single_body + _patch_fanout_churn), lambda_churn_incontainer, and --
CORRECTED vs the plan's prose (see tests/ducklake_neon_smoke_test's w7_build_file2.py manifest
note; lambda_ec_gates.py, not lambda_ops_gates.py, is where these are actually defined, per the
facade's own import block) -- lambda_reader and lambda_warm_reuse/lambda_warm_reuse_writer (with
the _warm_reuse_invoker helper).
"""

from __future__ import annotations

import json

import pytest

import scripts.ducklake_neon_smoke_test as smoke
from scripts.ducklake_smoke import core
from src.common.ducklake_version import pinned_duckdb_version
from tests.fixtures.ducklake_smoke_fakes import _Resp


def _patch_gate(monkeypatch, payload, status=200):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(core, "_sigv4_invoke", lambda url, p, **kw: _Resp(status, payload))


def test_lambda_attach_ok(monkeypatch, capsys):
    pin = pinned_duckdb_version()
    _patch_gate(monkeypatch, {"version": pin, "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
    smoke.lambda_attach()
    assert f"LAMBDA_ATTACH OK version={pin} source=layer" in capsys.readouterr().out


def test_lambda_attach_wrong_version_fails(monkeypatch):
    _patch_gate(monkeypatch, {"version": "1.5.2", "source": "layer", "connect_ms": 1, "commit_ms": 1})
    with pytest.raises(smoke.SmokeTestFailure, match="LAMBDA_ATTACH FAIL"):
        smoke.lambda_attach()


def test_lambda_ingress_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: "https://w")
    monkeypatch.setattr(core, "_sigv4_invoke", lambda url, p, **kw: _Resp(200 if kw.get("sign", True) else 403))
    smoke.lambda_ingress()
    assert "INGRESS OK unsigned=403 signed=200" in capsys.readouterr().out


def test_lambda_ingress_fails_when_unsigned_allowed(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: "https://w")
    monkeypatch.setattr(core, "_sigv4_invoke", lambda url, p, **kw: _Resp(200))  # unsigned also 200
    with pytest.raises(smoke.SmokeTestFailure, match="INGRESS FAIL"):
        smoke.lambda_ingress()


def test_lambda_idempotency_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"ulid_reused": True, "history_rows": 1, "current_rows": 1})
    smoke.lambda_idempotency()
    assert "IDEMPOTENCY OK ulid_reused=true history_rows=1 current_rows=1" in capsys.readouterr().out


def test_lambda_idempotency_fails(monkeypatch):
    _patch_gate(monkeypatch, {"ulid_reused": True, "history_rows": 2, "current_rows": 1})
    with pytest.raises(smoke.SmokeTestFailure, match="IDEMPOTENCY FAIL"):
        smoke.lambda_idempotency()


def test_lambda_partition_ok(monkeypatch, capsys):
    _patch_gate(
        monkeypatch,
        {
            "history_pruned": True,
            "history_files_scanned": 1,
            "history_total": 3,
            "current_partitions_scanned": 1,
            "current_files_scanned": 1,
            "current_total": 4,
        },
    )
    smoke.lambda_partition()
    assert "PARTITION OK history_pruned=true" in capsys.readouterr().out


def test_lambda_partition_fails(monkeypatch):
    _patch_gate(
        monkeypatch,
        {
            "history_pruned": False,
            "history_files_scanned": 3,
            "history_total": 3,
            "current_partitions_scanned": 2,
            "current_files_scanned": 4,
            "current_total": 4,
        },
    )
    with pytest.raises(smoke.SmokeTestFailure, match="PARTITION FAIL"):
        smoke.lambda_partition()


def test_lambda_inlining_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"inlined_rows": 0, "s3_parquet": 2, "occ_conflicts_handled": True})
    smoke.lambda_inlining()
    assert "INLINING OK inlined_rows=0 s3_parquet=2" in capsys.readouterr().out


def test_lambda_inlining_fails(monkeypatch):
    _patch_gate(monkeypatch, {"inlined_rows": 5, "s3_parquet": 0, "occ_conflicts_handled": True})
    with pytest.raises(smoke.SmokeTestFailure, match="INLINING FAIL"):
        smoke.lambda_inlining()


def test_lambda_loudfail_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"schema_reject": "raised", "occ_exhaust": "raised", "silent_drop": False})
    smoke.lambda_loudfail()
    assert "LOUDFAIL OK schema_reject=raised occ_exhaust=raised silent_drop=false" in capsys.readouterr().out


def test_lambda_loudfail_fails(monkeypatch):
    _patch_gate(monkeypatch, {"schema_reject": "not_raised", "occ_exhaust": "raised", "silent_drop": False})
    with pytest.raises(smoke.SmokeTestFailure, match="LOUDFAIL FAIL"):
        smoke.lambda_loudfail()


def _churn_single_body(**kw) -> dict:
    """Default per-invocation churn_single response body for fan-out lambda_churn tests."""
    base = {
        "ok": True,
        "latency_ms": 500.0,
        "collided": False,
        "connect_ms": 120.0,
        "commit_ms": 380.0,
        "cpu_ms": 200.0,
        "occ_retries": 0,
        "wall_ms": 500.0,
    }
    base.update(kw)
    return base


def _patch_fanout_churn(monkeypatch, per_invocation_body=None):
    """Patch _function_url + _sigv4_invoke for the fan-out lambda_churn (including pre-warm phase).

    Handles three payload types: attach_check (pre-warm), churn_single setup=True, churn_single normal.
    """
    monkeypatch.setattr(core, "_function_url", lambda role: "https://writer")
    body = per_invocation_body or _churn_single_body()

    def fake_invoke(url, payload, **kw):
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        return _Resp(200, body)

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)


def test_lambda_churn_fanout_ok(monkeypatch, capsys):
    _patch_fanout_churn(monkeypatch)
    smoke.lambda_churn()
    out = capsys.readouterr().out
    assert "CHURN OK collision_rate=0.0 p95_commit_ms=500.0 endpoint=direct" in out
    assert "within_budget=True" in out
    assert "wall_cpu_ratio=2.5" in out


def test_lambda_churn_fanout_n_concurrent_calls(monkeypatch):
    """CHURN_WRITERS pre-warm + 1 setup + CHURN_WRITERS fan-out calls are issued in order."""
    call_payloads: list[dict] = []
    monkeypatch.setattr(core, "_function_url", lambda role: "https://writer")

    def fake_invoke(url, payload, **kw):
        call_payloads.append(dict(payload))
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        return _Resp(200, _churn_single_body())

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.lambda_churn()
    prewarm_calls = [p for p in call_payloads if p.get("action") == "attach_check"]
    setup_calls = [p for p in call_payloads if p.get("setup")]
    normal_calls = [p for p in call_payloads if not p.get("setup") and p.get("action") != "attach_check"]
    assert len(prewarm_calls) == smoke.CHURN_WRITERS
    assert len(setup_calls) == 1
    assert len(normal_calls) == smoke.CHURN_WRITERS
    assert all(p.get("action") == "churn_single" for p in normal_calls)
    assert sorted(p.get("writer_id") for p in normal_calls) == list(range(smoke.CHURN_WRITERS))


def test_lambda_churn_fanout_aggregation_breakdown(monkeypatch, capsys):
    """Aggregated breakdown fields are computed correctly from N per-invocation bodies."""
    _patch_fanout_churn(monkeypatch, _churn_single_body(connect_ms=120.0, cpu_ms=200.0, wall_ms=500.0))
    smoke.lambda_churn()
    out = capsys.readouterr().out
    assert "p95_connect_ms=120.0" in out
    assert "wall_cpu_ratio=2.5" in out
    assert "total_occ_retries=0" in out


def test_lambda_churn_fanout_collision_rate_loudfail(monkeypatch):
    """Collision rate over budget triggers SmokeTestFailure."""
    monkeypatch.setattr(core, "_function_url", lambda role: "https://writer")
    idx = [0]

    def fake_invoke(url, payload, **kw):
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        collided = idx[0] < (smoke.CHURN_WRITERS // 2 + 1)
        idx[0] += 1
        return _Resp(200, _churn_single_body(collided=collided))

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN FAIL"):
        smoke.lambda_churn()


def test_lambda_churn_fanout_latency_loudfail(monkeypatch):
    """p95 wall latency over budget triggers SmokeTestFailure."""
    _patch_fanout_churn(
        monkeypatch,
        _churn_single_body(latency_ms=smoke.COMMIT_LATENCY_BUDGET_MS + 1.0, wall_ms=smoke.COMMIT_LATENCY_BUDGET_MS + 1.0),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN FAIL"):
        smoke.lambda_churn()


def test_churn_constants_imported_from_runtime():
    from src.common import ducklake_runtime

    assert smoke.OCC_COLLISION_RATE_BUDGET == ducklake_runtime.OCC_COLLISION_RATE_BUDGET
    assert smoke.COMMIT_LATENCY_BUDGET_MS == ducklake_runtime.COMMIT_LATENCY_BUDGET_MS
    assert smoke.CHURN_WRITERS == ducklake_runtime.CHURN_WRITERS
    assert smoke.CHURN_WRITES_PER_WRITER == ducklake_runtime.CHURN_WRITES_PER_WRITER


def test_lambda_churn_incontainer_prints_breakdown(monkeypatch, capsys):
    """lambda_churn_incontainer prints diagnostic breakdown and does NOT raise on over-budget."""
    _patch_gate(
        monkeypatch,
        {
            "collision_rate": 0.0,
            "p95_commit_ms": 8780.0,
            "within_budget": False,
            "endpoint": "direct",
            "breakdown": {
                "wall_cpu_ratio": 10.35,
                "p95_connect_ms": 900.0,
                "p95_cpu_ms": 850.0,
                "total_occ_retries": 0,
            },
        },
    )
    smoke.lambda_churn_incontainer()  # must NOT raise
    out = capsys.readouterr().out
    assert "CHURN_INCONTAINER" in out
    assert "wall_cpu_ratio=10.35" in out
    assert "within_budget=False" in out


def test_lambda_churn_incontainer_budget_pass_still_no_raise(monkeypatch, capsys):
    """lambda_churn_incontainer does not raise even when within_budget=True (always diagnostic)."""
    _patch_gate(monkeypatch, {"collision_rate": 0.0, "p95_commit_ms": 500.0, "within_budget": True, "breakdown": {}})
    smoke.lambda_churn_incontainer()
    assert "CHURN_INCONTAINER" in capsys.readouterr().out


def test_lambda_reader_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": True})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.lambda_reader()
    assert "READER OK rows=3 write_denied=true" in capsys.readouterr().out


def _warm_reuse_invoker():
    """Fake _sigv4_invoke: 1st attach_check is cold (reused=False), subsequent are warm (reused=True)."""
    state = {"attach_calls": 0}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "reset_warm_connection":
            state["attach_calls"] = 0
            return _Resp(200, {"ok": True, "reset": True})
        if action == "attach_check":
            state["attach_calls"] += 1
            cold = state["attach_calls"] == 1
            return _Resp(200, {"ok": True, "connect_ms": 80.0 if cold else 0.0, "connect_reused": not cold})
        if action == "write":
            return _Resp(200, {"ok": True, "occ_retries": 0})
        return _Resp(200, {"ok": True})

    return fake_invoke


def test_lambda_warm_reuse_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(core, "_sigv4_invoke", _warm_reuse_invoker())
    smoke.lambda_warm_reuse(json_output=True)
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["role"] == "reader"
    assert result["warm_reuse_observed"] is True
    assert result["warm_connect_ms"] == 0.0
    assert result["reconnect_ok"] is True


def test_lambda_warm_reuse_writer_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(core, "_sigv4_invoke", _warm_reuse_invoker())
    smoke.lambda_warm_reuse_writer(json_output=True)
    result = json.loads(capsys.readouterr().out)
    assert result["role"] == "writer"
    assert result["warm_reuse_observed"] is True
    assert result["write_ok"] is True


def test_lambda_warm_reuse_fails_when_no_reuse(monkeypatch):
    """If reuse is never observed (connect_reused stays False), the gate loud-fails."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")

    def never_reused(url, payload, **kw):
        if payload["action"] == "attach_check":
            return _Resp(200, {"ok": True, "connect_ms": 80.0, "connect_reused": False})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(core, "_sigv4_invoke", never_reused)
    with pytest.raises(smoke.SmokeTestFailure, match="warm reuse not observed"):
        smoke.lambda_warm_reuse()


def test_lambda_reader_boundary_broken_fails(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": False})  # boundary broken

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="READER FAIL"):
        smoke.lambda_reader()
