"""CONCERN: scripts/ducklake_smoke/lambda_ops_gates.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: ops_read_your_write,
ops_churn_regate (delegates to lambda_ec_gates.lambda_churn), and catalog_restore_drill.
connect_probe and lambda_append_only (also owned by lambda_ops_gates.py) have no direct unit test
in the monolith -- connect_probe is exercised only via the facade-interception test in
test_facade.py; lambda_append_only has no unit test at all (V3-only coverage).
"""

from __future__ import annotations

import pytest

import scripts.ducklake_neon_smoke_test as smoke
from scripts.ducklake_smoke import core, lambda_ec_gates
from tests.fixtures.ducklake_smoke_fakes import _Resp


def test_ops_read_your_write_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}
    written = {}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "write_ops":
            written.update(payload["record"])
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            if payload["record"]["id"].startswith("test-absent"):
                return _Resp(409, {"error_type": "referential"})
            state["status"] = payload["record"]["status"]
            return _Resp(200, {"ok": True})
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        return _Resp(200, {})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.ops_read_your_write()
    assert "OPS_RYW OK" in capsys.readouterr().out
    # The probe row persists (writer has no delete verb); it must carry the DQ NOT-NULL columns
    # so it does not red the ops_recommendations data-quality checks while it lingers.
    for col in ("automatable", "file", "context", "acceptance"):
        assert written.get(col) is not None, f"probe missing DQ-required column {col!r}"


def test_ops_read_your_write_absent_not_409_fails(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        if action == "update_ops" and not payload["record"]["id"].startswith("test-absent"):
            state["status"] = "closed"
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            return _Resp(200, {"ok": True})  # absent update wrongly succeeds -> boundary broken
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="expected 409"):
        smoke.ops_read_your_write()


def test_ops_churn_regate_delegates(monkeypatch, capsys):
    monkeypatch.setattr(lambda_ec_gates, "lambda_churn", lambda profile=None, region="eu-west-2": None)
    smoke.ops_churn_regate()
    assert "OPS_CHURN_REGATE OK" in capsys.readouterr().out


def test_catalog_restore_drill_ok(monkeypatch, capsys):
    # T2.19: catalog_restore_drill now INVOKES the maintenance restore_drill action over 443 (the
    # pg_dump/pg_restore runs inside AWS -- no Neon 5432 from CC-web). Mock the URL + the invoke.
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, p, **kw: _Resp(200, {"ok": True, "restored": True, "probe_id": "drill-probe", "pg_version": "16"}),
    )
    smoke.catalog_restore_drill()
    assert "CATALOG_RESTORE_DRILL OK" in capsys.readouterr().out


def test_catalog_restore_drill_probe_lost_fails(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(core, "_sigv4_invoke", lambda url, p, **kw: _Resp(200, {"ok": True, "restored": False}))
    with pytest.raises(smoke.SmokeTestFailure, match="did not restore"):
        smoke.catalog_restore_drill()
