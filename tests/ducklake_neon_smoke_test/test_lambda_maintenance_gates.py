"""CONCERN: scripts/ducklake_smoke/lambda_maintenance_gates.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: the four
lambda_maintenance_merge gate tests (ok, empty-smoke-catalog-ok, files-grew-fails, not-ok-fails).
"""

from __future__ import annotations

import pytest

import scripts.ducklake_neon_smoke_test as smoke
from scripts.ducklake_smoke import core
from tests.fixtures.ducklake_smoke_fakes import _Resp


def test_lambda_maintenance_merge_ok(monkeypatch, capsys):
    """VP9: maintenance merge with force_recreate_tables=True; asserts files_after_merge <= files_before."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    invoked = {}

    def fake_invoke(url, payload, **kw):
        invoked["payload"] = payload
        return _Resp(200, {"ok": True, "files_before": 3, "files_after_merge": 2, "elapsed_ms": 45.0})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.lambda_maintenance_merge()
    out = capsys.readouterr().out
    assert "MAINTENANCE_MERGE OK files_before=3 files_after_merge=2" in out
    assert invoked["payload"] == {"action": "merge", "force_recreate_tables": True}


def test_lambda_maintenance_merge_empty_smoke_catalog_ok(monkeypatch, capsys):
    """VP9: works on a fresh environment where smoke tables were just created (files_before=0)."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": True, "files_before": 0, "files_after_merge": 0, "elapsed_ms": 12.0}),
    )
    smoke.lambda_maintenance_merge()
    assert "MAINTENANCE_MERGE OK files_before=0 files_after_merge=0" in capsys.readouterr().out


def test_lambda_maintenance_merge_files_grew_fails(monkeypatch):
    """VP9: loud-fail when files_after_merge > files_before (merge expanded the catalog)."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": True, "files_before": 2, "files_after_merge": 5}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="files grew after merge"):
        smoke.lambda_maintenance_merge()


def test_lambda_maintenance_merge_not_ok_fails(monkeypatch):
    """VP9: loud-fail when maintenance returns ok=False."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": False, "error": "catalog error"}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="MAINTENANCE_MERGE FAIL"):
        smoke.lambda_maintenance_merge()


def test_lambda_maintenance_gc_ok(monkeypatch, capsys):
    """VP10: gc with force_recreate_tables=True (rec-2115 gap-1); asserts files_after <= files_before."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    invoked = {}

    def fake_invoke(url, payload, **kw):
        invoked["payload"] = payload
        return _Resp(
            200,
            {
                "ok": True,
                "breaker_stats": {"breaker_tripped": False},
                "files_before": 5,
                "files_after": 3,
                "snapshots_expired": 1,
                "files_cleaned": 2,
                "orphans_deleted": 0,
            },
        )

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.lambda_maintenance_gc()
    out = capsys.readouterr().out
    assert "MAINTENANCE_GC OK files_before=5 files_after=3" in out
    assert invoked["payload"] == {"action": "gc", "force_recreate_tables": True}


def test_lambda_maintenance_gc_fresh_smoke_catalog_ok(monkeypatch, capsys):
    """rec-2115 gap-1: force_recreate_tables=True means gc no longer 502s on a fresh smoke catalog
    (files_before=0 when the smoke tables were just created)."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(
            200,
            {
                "ok": True,
                "breaker_stats": {"breaker_tripped": False},
                "files_before": 0,
                "files_after": 0,
                "snapshots_expired": 0,
                "files_cleaned": 0,
                "orphans_deleted": 0,
            },
        ),
    )
    smoke.lambda_maintenance_gc()
    assert "MAINTENANCE_GC OK files_before=0 files_after=0" in capsys.readouterr().out


def test_lambda_maintenance_gc_breaker_tripped_fails(monkeypatch):
    """VP10: loud-fail when the circuit breaker trips unexpectedly."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": True, "breaker_stats": {"breaker_tripped": True}}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="circuit breaker tripped"):
        smoke.lambda_maintenance_gc()


def test_lambda_maintenance_gc_not_ok_fails(monkeypatch):
    """VP10: loud-fail when maintenance returns ok=False."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": False, "error": "catalog error"}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="MAINTENANCE_GC FAIL"):
        smoke.lambda_maintenance_gc()
