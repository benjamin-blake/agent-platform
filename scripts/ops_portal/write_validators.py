"""Write-time rec-field content validation, driven by config/agent/data_quality/ops.yaml.

Owner-concern: the three explicit content-quality checks (path syntax, context length,
not-null) plus the YAML-driven write_time validator loader that file_rec() (kept in the
facade) runs before any write reaches the DuckLake writer.
"""

from __future__ import annotations

import re
from typing import Callable

import yaml

from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.ops_portal._common import ROOT

_OPS_YAML_PATH = ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
_write_time_validators_cache: dict[str, list] = {}


def _validate_file_path(path: str) -> None:
    """Raise ValueError if path is absolute or uses backslash separators."""
    if not path:
        return
    if path.startswith("/"):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Unix path): {path!r}")
    if re.match(r"[A-Za-z]:[/\\]", path):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Windows path): {path!r}")
    if "\\" in path:
        raise ValueError(f"file must use forward slashes as path separators (got backslash): {path!r}")


def _validate_context_length(text: str) -> None:
    """Raise ValueError if stripped context is shorter than 80 characters."""
    if not text:
        return
    stripped_len = len(text.strip())
    if stripped_len < 80:
        raise ValueError(
            f"context must be at least 80 stripped characters (got {stripped_len}). "
            "Answer 'what problem does this solve and why now?'"
        )


def _check_not_null(v: object, col: str) -> None:
    if v is None or not str(v).strip():
        raise ValueError(f"required field '{col}' must be non-empty")


def _load_write_time_validators(table: str) -> list[tuple[str, Callable]]:
    """Load write-time validators from ops.yaml for the given table.

    Returns a list of (column_name, validator_fn) tuples for every test entry
    with write_time: true. Result is cached to avoid repeated YAML reads.
    """
    if table in _write_time_validators_cache:
        return _write_time_validators_cache[table]

    try:
        data = yaml.safe_load(_OPS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        _write_time_validators_cache[table] = []
        return []

    columns = data.get("tables", {}).get(table, {}).get("columns", {})
    validators: list[tuple[str, Callable]] = []

    for col_name, col_def in columns.items():
        if not isinstance(col_def, dict):
            continue
        for test_entry in col_def.get("tests", []):
            if not isinstance(test_entry, dict):
                continue
            for test_name, params in test_entry.items():
                if not isinstance(params, dict) or not params.get("write_time"):
                    continue
                if test_name == "not_null":
                    validators.append((col_name, _check_not_null))
                elif test_name == "accepted_values":
                    allowed = list(params.get("values", []))

                    def _make_accepted(values: list, column: str) -> Callable:
                        def _check(v: object, col: str) -> None:
                            if v is not None and str(v).strip() and str(v) not in values:
                                raise ValueError(f"{col} must be one of {values!r}, got {str(v)!r}")

                        return _check

                    validators.append((col_name, _make_accepted(allowed, col_name)))
                elif test_name == "path_syntax":
                    validators.append((col_name, lambda v, col: _validate_file_path(str(v) if v else "")))
                elif test_name == "acceptance_lint":

                    def _check_acceptance(v: object, col: str) -> None:
                        ok, msg = lint_acceptance_command(str(v) if v else "")
                        if not ok:
                            raise ValueError(msg)

                    validators.append((col_name, _check_acceptance))
                elif test_name == "expression" and isinstance(params.get("python"), str):
                    validators.append((col_name, lambda v, col: _validate_context_length(str(v) if v else "")))

    _write_time_validators_cache[table] = validators
    return validators
