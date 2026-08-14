"""Log-storage routing parity check (rec-3059 first-wave enforcer build).

Promotes the assertion formerly living only in
tests/s3_log_store/test_write_through_registry.py::TestLogStorageRegistry::test_anti_drift to a
registered check: asserts docs/contracts/log-storage.yaml's routing block equals
scripts/s3_log_store.py's FALLBACK_OPS_TABLE_ROUTING / FALLBACK_PRIORITY_QUEUE_KEY constants.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_NAME = "log-storage.yaml"


@registry.register("validate_log_storage_registry", owner="platform")
def validate_log_storage_registry(failed: list[str], *, contracts_dir: Path | None = None) -> None:
    """Fail if log-storage.yaml's routing block diverges from s3_log_store.py's FALLBACK constants."""
    print("\n=== Log-storage routing parity ===")
    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    path = target_dir / _CONTRACT_NAME

    if not path.is_file():
        failed.append(f"Log-storage routing parity: {path} not found")
        registry.skipped(f"{_CONTRACT_NAME} not found")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Log-storage routing parity: could not read/parse {path}: {exc}")
        registry.skipped(f"{_CONTRACT_NAME} not parseable")
        return

    routing = data.get("routing") if isinstance(data, dict) else None
    if not isinstance(routing, dict) or not routing:
        failed.append(f"Log-storage routing parity: {path} missing or empty top-level 'routing' block")
        registry.skipped(f"{_CONTRACT_NAME} missing or empty top-level 'routing' block")
        return

    declared_table_routing = routing.get("ops_table_routing")
    declared_queue_key = routing.get("priority_queue_key")
    if (
        not isinstance(declared_table_routing, dict)
        or not declared_table_routing
        or not isinstance(declared_queue_key, str)
        or not declared_queue_key
    ):
        failed.append(
            f"Log-storage routing parity: {path} 'routing' is missing a non-empty "
            "ops_table_routing mapping or priority_queue_key string"
        )
        registry.skipped(f"{_CONTRACT_NAME} 'routing' missing ops_table_routing or priority_queue_key")
        return

    from scripts import s3_log_store  # noqa: PLC0415

    table_routing_matches = declared_table_routing == s3_log_store.FALLBACK_OPS_TABLE_ROUTING
    queue_key_matches = declared_queue_key == s3_log_store.FALLBACK_PRIORITY_QUEUE_KEY
    registry.examined(len(declared_table_routing) + 1, unit="routing_entries")
    if not table_routing_matches or not queue_key_matches:
        failed.append(
            f"Log-storage routing parity: {_CONTRACT_NAME} declares "
            f"ops_table_routing={declared_table_routing} priority_queue_key={declared_queue_key!r} but "
            f"s3_log_store.py's FALLBACK_OPS_TABLE_ROUTING={s3_log_store.FALLBACK_OPS_TABLE_ROUTING} "
            f"FALLBACK_PRIORITY_QUEUE_KEY={s3_log_store.FALLBACK_PRIORITY_QUEUE_KEY!r}"
        )
        return

    print(f"  PASS: {_CONTRACT_NAME} routing block matches s3_log_store.py's FALLBACK constants.")
