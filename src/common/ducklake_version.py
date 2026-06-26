"""DuckLake/DuckDB version SSOT loader (OQ.12 / PLAN-duckdb-pin-bump-1-5-4).

Single source of truth: config/lambda/ducklake/version.yaml.
Imports stdlib + pyyaml ONLY (no duckdb/ulid) so build_lambda can import this
without the heavy Lambda deps. Never raises at import; fails loudly on explicit
call if the config is missing or malformed (Decision 55 / AGENTS.md no-import-raise).

Env override: DUCKLAKE_VERSION_CONFIG -- set to a custom version.yaml path to
override the default (mirrors the DUCKLAKE_FIELD_SEMANTICS_PATH pattern).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_VERSION_CONFIG_ENV = "DUCKLAKE_VERSION_CONFIG"
_DEFAULT_VERSION_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "lambda" / "ducklake" / "version.yaml"


def _version_config_path() -> Path:
    """Resolve the version config YAML path (env override for tests / Lambda-bundle relocation)."""
    override = os.environ.get(_VERSION_CONFIG_ENV)
    return Path(override) if override else _DEFAULT_VERSION_CONFIG_PATH


@lru_cache(maxsize=4)
def _load_version_config_cached(path_str: str) -> dict:
    import yaml  # noqa: PLC0415 -- deferred to avoid import-time cost when unused

    raw = Path(path_str).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"ducklake version config at {path_str!r} must be a YAML mapping, got {type(data)}")
    if "duckdb_version" not in data:
        raise ValueError(f"ducklake version config at {path_str!r} is missing required key 'duckdb_version'")
    return data


def _load_version_config(path: str | Path | None = None) -> dict:
    """Load + cache the version config. Pass `path` to override (tests)."""
    resolved = Path(path) if path is not None else _version_config_path()
    return _load_version_config_cached(str(resolved))


def pinned_duckdb_version(path: str | Path | None = None) -> str:
    """Return the pinned DuckDB version string from the SSOT (e.g. '1.5.4')."""
    return _load_version_config(path)["duckdb_version"]


def ducklake_format(path: str | Path | None = None) -> str:
    """Return the DuckLake catalog format version from the SSOT (e.g. 'v1.0')."""
    return _load_version_config(path).get("ducklake_format", "v1.0")


def extension_platform(path: str | Path | None = None) -> str:
    """Return the extension platform string from the SSOT (e.g. 'linux_amd64')."""
    return _load_version_config(path).get("extension_platform", "linux_amd64")
