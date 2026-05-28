"""Precision context injection for recommendation writes (Decision 66).

Surfaces ops.yaml field semantics and the source registry to agents before they
call file_rec(), preventing semantically thin but structurally valid records.

Public API:
    load_source_registry()   -- parse source_registry.yaml; cached after first call
    validate_source()        -- raise ValueError for unregistered source values
    get_rec_write_guidance() -- return field semantics + registry for agent context
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_REGISTRY = _ROOT / "config" / "agent" / "data_quality" / "source_registry.yaml"
_DEFAULT_OPS_YAML = _ROOT / "config" / "agent" / "data_quality" / "ops.yaml"


@lru_cache(maxsize=4)
def _load_registry_cached(registry_path: Path) -> tuple[dict, ...]:
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return tuple(data.get("entries", []))


def load_source_registry(registry_path: Path | None = None) -> list[dict]:
    """Return all entries from source_registry.yaml as a list of dicts."""
    path = registry_path or _DEFAULT_REGISTRY
    return list(_load_registry_cached(path))


def validate_source(value: str, registry_path: Path | None = None) -> None:
    """Raise ValueError if value is not a registered canonical_id.

    Args:
        value: The source string to validate.
        registry_path: Override path for source_registry.yaml (used in tests).

    Raises:
        ValueError: If value is not in the registry's canonical_id list.
    """
    entries = load_source_registry(registry_path)
    valid_ids = {e["canonical_id"] for e in entries}
    if value not in valid_ids:
        raise ValueError(
            f"Unknown source '{value}'. Register in config/agent/data_quality/source_registry.yaml before filing."
        )


def get_rec_write_guidance(
    ops_yaml_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return field semantics from ops.yaml augmented with registry data for source.

    Agents MUST call this before file_rec() so that field semantics are in context
    at composition time (Decision 66 -- Precision Context Injection).

    Returns:
        Dict keyed by column name. Each value has at minimum:
            "description": str
            "semantics": str
        The "source" entry additionally carries:
            "registered_values": list[str]  -- all canonical_ids from source_registry.yaml
    """
    ops_path = ops_yaml_path or _DEFAULT_OPS_YAML
    data = yaml.safe_load(ops_path.read_text(encoding="utf-8"))

    guidance: dict[str, dict[str, Any]] = {}
    tables = data.get("tables", {})
    for _table_name, table_def in tables.items():
        columns = table_def.get("columns", {})
        for col_name, col_def in columns.items():
            if col_name in guidance:
                continue
            entry: dict[str, Any] = {
                "description": col_def.get("description", ""),
                "semantics": col_def.get("semantics", ""),
            }
            if col_name == "source":
                entries = load_source_registry(registry_path)
                entry["registered_values"] = [e["canonical_id"] for e in entries]
            guidance[col_name] = entry

    return guidance
