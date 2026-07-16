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
