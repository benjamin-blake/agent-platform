"""Tests for scripts/sync_ducklake_version -- 100% coverage."""

from __future__ import annotations

import scripts.sync_ducklake_version as sdv

_PIN = "1.5.4"


def _mock_version(monkeypatch, version: str = _PIN):
    monkeypatch.setattr(sdv, "_get_pinned_version", lambda: version)


# ---------------------------------------------------------------------------
# _get_pinned_version -- real importlib.util path (no mock)
# ---------------------------------------------------------------------------


def test_get_pinned_version_real():
    """Exercises _get_pinned_version() via importlib.util (the actual non-mocked path)."""
    version = sdv._get_pinned_version()
    assert version == _PIN, f"Expected {_PIN!r}, got {version!r}"


def test_get_pinned_version_raises_when_spec_none(monkeypatch):
    """RuntimeError is raised (not AssertionError) when spec_from_file_location returns None."""
    import importlib.util  # noqa: PLC0415

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: None)
    import pytest  # noqa: PLC0415

    with pytest.raises(RuntimeError, match="Cannot load src.common.ducklake_version"):
        sdv._get_pinned_version()


# ---------------------------------------------------------------------------
# _expected_floor_line
# ---------------------------------------------------------------------------


def test_expected_floor_line_format():
    line = sdv._expected_floor_line("1.5.4")
    assert line.startswith("duckdb>=1.5.4")
    assert "sync_ducklake_version" in line
    assert "version.yaml" in line


# ---------------------------------------------------------------------------
# sync -- rewrite mode
# ---------------------------------------------------------------------------


def test_sync_rewrites_old_floor(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("requests>=2.0\nduckdb>=1.5.3  # old comment\nboto3>=1.0\n", encoding="utf-8")
    result = sdv.sync(check_only=False, requirements_path=req)
    assert result is True
    content = req.read_text(encoding="utf-8")
    assert "duckdb>=1.5.4" in content
    assert "1.5.3" not in content
    assert "requests>=2.0" in content
    assert "boto3>=1.0" in content


def test_sync_idempotent_when_already_in_sync(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    expected_line = sdv._expected_floor_line(_PIN)
    req.write_text(f"requests>=2.0\n{expected_line}\nboto3>=1.0\n", encoding="utf-8")
    original = req.read_text(encoding="utf-8")
    result = sdv.sync(check_only=False, requirements_path=req)
    assert result is True
    assert req.read_text(encoding="utf-8") == original


def test_sync_rewrites_exact_pin_to_floor(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("duckdb==1.5.3\n", encoding="utf-8")
    result = sdv.sync(check_only=False, requirements_path=req)
    assert result is True
    content = req.read_text(encoding="utf-8")
    assert "duckdb>=1.5.4" in content


def test_sync_with_inline_comment_rewrites_version_token_only(tmp_path, monkeypatch):
    """A line with inline comment (today's format) is rewritten on the version token only."""
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "duckdb>=1.5.3  # floor is load-bearing: >=1.5.3 ships the ducklake-extension-capable runtime"
        " (src/common/ducklake_spike.py INSTALL ducklake); Lambda layer pins ==1.5.3 lockstep"
        " (ducklake_runtime.py PINNED_DUCKDB_VERSION)\n",
        encoding="utf-8",
    )
    result = sdv.sync(check_only=False, requirements_path=req)
    assert result is True
    content = req.read_text(encoding="utf-8")
    assert "duckdb>=1.5.4" in content
    assert "1.5.3" not in content


def test_sync_appends_when_no_duckdb_line(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("requests>=2.0\n", encoding="utf-8")
    result = sdv.sync(check_only=False, requirements_path=req)
    assert result is True
    content = req.read_text(encoding="utf-8")
    assert "duckdb>=1.5.4" in content


# ---------------------------------------------------------------------------
# sync -- check mode
# ---------------------------------------------------------------------------


def test_check_passes_when_in_sync(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    expected_line = sdv._expected_floor_line(_PIN)
    req.write_text(f"{expected_line}\n", encoding="utf-8")
    result = sdv.sync(check_only=True, requirements_path=req)
    assert result is True


def test_check_detects_drift(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("duckdb>=1.5.3  # old\n", encoding="utf-8")
    result = sdv.sync(check_only=True, requirements_path=req)
    assert result is False


def test_check_detects_missing_line(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("requests>=2.0\n", encoding="utf-8")
    result = sdv.sync(check_only=True, requirements_path=req)
    assert result is False


def test_check_does_not_write_file(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("duckdb>=1.5.3\n", encoding="utf-8")
    original_mtime = req.stat().st_mtime
    sdv.sync(check_only=True, requirements_path=req)
    assert req.stat().st_mtime == original_mtime


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


def test_main_rewrite_returns_0(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("duckdb>=1.5.3\n", encoding="utf-8")
    monkeypatch.setattr(sdv, "REQUIREMENTS_PATH", req)
    assert sdv.main([]) == 0


def test_main_check_passes_returns_0(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text(sdv._expected_floor_line(_PIN) + "\n", encoding="utf-8")
    monkeypatch.setattr(sdv, "REQUIREMENTS_PATH", req)
    assert sdv.main(["--check"]) == 0


def test_main_check_fails_returns_1(tmp_path, monkeypatch):
    _mock_version(monkeypatch)
    req = tmp_path / "requirements.txt"
    req.write_text("duckdb>=1.5.3\n", encoding="utf-8")
    monkeypatch.setattr(sdv, "REQUIREMENTS_PATH", req)
    assert sdv.main(["--check"]) == 1
