"""Tests for src/common/ducklake_version -- 100% coverage of the SSOT loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import src.common.ducklake_version as dv  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_version_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "version.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _clear_cache():
    dv._load_version_config_cached.cache_clear()


# ---------------------------------------------------------------------------
# pinned_duckdb_version -- reads the real config
# ---------------------------------------------------------------------------


def test_pinned_duckdb_version_reads_real_config():
    _clear_cache()
    pin = dv.pinned_duckdb_version()
    assert pin == "1.5.4", f"Expected 1.5.4, got {pin!r}"


def test_ducklake_format_reads_real_config():
    _clear_cache()
    fmt = dv.ducklake_format()
    assert fmt == "v1.0"


def test_extension_platform_reads_real_config():
    _clear_cache()
    plat = dv.extension_platform()
    assert plat == "linux_amd64"


# ---------------------------------------------------------------------------
# env override -- DUCKLAKE_VERSION_CONFIG
# ---------------------------------------------------------------------------


def test_env_override_flows_through_pinned_duckdb_version(tmp_path, monkeypatch):
    p = _write_version_yaml(
        tmp_path,
        'duckdb_version: "9.9.9"\nducklake_format: "v2.0"\nextension_platform: "arm64"\n',
    )
    _clear_cache()
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    assert dv.pinned_duckdb_version() == "9.9.9"
    assert dv.ducklake_format() == "v2.0"
    assert dv.extension_platform() == "arm64"
    _clear_cache()


def test_env_override_absent_uses_default(monkeypatch):
    monkeypatch.delenv(dv._VERSION_CONFIG_ENV, raising=False)
    _clear_cache()
    assert dv._version_config_path() == dv._DEFAULT_VERSION_CONFIG_PATH


# ---------------------------------------------------------------------------
# cascade assertion -- sentinel version flows through
# ---------------------------------------------------------------------------


def test_cascade_sentinel_version(tmp_path, monkeypatch):
    """Overriding the one SSOT value must flow through pinned_duckdb_version()."""
    p = _write_version_yaml(
        tmp_path,
        'duckdb_version: "7.7.7"\nducklake_format: "v1.0"\nextension_platform: "linux_amd64"\n',
    )
    _clear_cache()
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    assert dv.pinned_duckdb_version() == "7.7.7"
    _clear_cache()


# ---------------------------------------------------------------------------
# caching
# ---------------------------------------------------------------------------


def test_repeated_calls_are_cached(tmp_path, monkeypatch):
    p = _write_version_yaml(
        tmp_path,
        'duckdb_version: "1.2.3"\nducklake_format: "v1.0"\nextension_platform: "linux_amd64"\n',
    )
    _clear_cache()
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    first = dv.pinned_duckdb_version()
    p.write_text('duckdb_version: "9.9.9"\n', encoding="utf-8")  # mutate -- should not be seen
    second = dv.pinned_duckdb_version()
    assert first == second == "1.2.3"  # cached value returned
    _clear_cache()


# ---------------------------------------------------------------------------
# fail-loud on bad config (explicit call only, never at import)
# ---------------------------------------------------------------------------


def test_missing_file_raises_on_explicit_call(tmp_path, monkeypatch):
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(tmp_path / "no_such.yaml"))
    _clear_cache()
    with pytest.raises(FileNotFoundError):
        dv.pinned_duckdb_version()
    _clear_cache()


def test_empty_file_raises_on_explicit_call(tmp_path, monkeypatch):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    _clear_cache()
    with pytest.raises((ValueError, yaml.YAMLError)):
        dv.pinned_duckdb_version()
    _clear_cache()


def test_malformed_yaml_raises_on_explicit_call(tmp_path, monkeypatch):
    p = tmp_path / "bad.yaml"
    p.write_text("not: valid: yaml:\n  - [broken", encoding="utf-8")
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    _clear_cache()
    with pytest.raises((ValueError, yaml.YAMLError)):
        dv.pinned_duckdb_version()
    _clear_cache()


def test_missing_duckdb_version_key_raises(tmp_path, monkeypatch):
    p = _write_version_yaml(tmp_path, 'ducklake_format: "v1.0"\n')
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    _clear_cache()
    with pytest.raises(ValueError, match="duckdb_version"):
        dv.pinned_duckdb_version()
    _clear_cache()


def test_non_mapping_yaml_raises(tmp_path, monkeypatch):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    monkeypatch.setenv(dv._VERSION_CONFIG_ENV, str(p))
    _clear_cache()
    with pytest.raises(ValueError, match="mapping"):
        dv.pinned_duckdb_version()
    _clear_cache()


# ---------------------------------------------------------------------------
# no-import-raise invariant (AGENTS.md)
# ---------------------------------------------------------------------------


def test_module_imports_without_error():
    """Importing the module must never raise -- pure defs only."""
    import importlib  # noqa: PLC0415

    importlib.reload(dv)
