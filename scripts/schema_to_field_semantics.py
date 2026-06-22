"""Generator: project Class A contracts -> config/lambda/ducklake/field_semantics.yaml.

Makes field_semantics.yaml a GENERATED projection of the ratified Class A contracts
(docs/contracts/ops_recommendations.yaml, docs/contracts/ops_decisions.yaml) so the
contract is the single source of truth for the DuckLake runtime field map (T2.33).

Non-contract content (smoke section, dormant tables, operational keys) lives in
config/lambda/ducklake/field_semantics.static.yaml (the sidecar). The generator
merges contract projection + sidecar to emit the whole field_semantics.yaml.

CLI:
  Default (no flags): regenerate and WRITE config/lambda/ducklake/field_semantics.yaml.
  --check:            regenerate in-memory, byte-compare against committed file;
                      exit non-zero on drift. NEVER auto-writes (Decision 55).
  --slice mechanical: emit only the mechanical projection (role/sql_type/nullable, no prose).
  --slice semantic:   emit only description/semantics per field (semantic write-guidance surface).

Migration-columns enforcement: every sidecar migration_columns entry must be a subset of
(and type-consistent with) the table's projected columns. Raises on violation (rec-2232).

Fail-closed rules:
  - Unmapped iceberg_type raises ValueError (never silently defaults).
  - contract.governance.merge_key must be present for each contract-backed table.
  - No exceptions raised at module import (AGENTS.md safety rule).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent
_CONTRACTS_DIR = ROOT / "docs" / "contracts"
_SIDECAR_PATH = ROOT / "config" / "lambda" / "ducklake" / "field_semantics.static.yaml"
_OUTPUT_PATH = ROOT / "config" / "lambda" / "ducklake" / "field_semantics.yaml"

_GENERATED_HEADER = """\
# GENERATED -- DO NOT EDIT (scripts/schema_to_field_semantics.py)
# Source of truth: docs/contracts/ops_recommendations.yaml, docs/contracts/ops_decisions.yaml
# Non-contract content: config/lambda/ducklake/field_semantics.static.yaml (the sidecar)
# To update: edit the contract or sidecar, then run: bin/venv-python -m scripts.schema_to_field_semantics
# Drift gate: bin/venv-python -m scripts.schema_to_field_semantics --check (non-zero on drift)
"""

_CONTRACT_TABLE_IDS = ("ops_recommendations", "ops_decisions")
_DORMANT_TABLE_IDS = ("ops_priority_queue", "ops_session_log", "ops_execution_plans")
# Append-only smoke tables (T1.14): no Class A contract, no current projection
# (write_mode: append_only -> current_table absent); spliced verbatim from the sidecar.
_SMOKE_TABLE_IDS = ("ops_smoke_events",)

_ICEBERG_TO_SQL: dict[str, str] = {
    "string": "VARCHAR",
    "boolean": "BOOLEAN",
    "long": "BIGINT",
    "int": "INTEGER",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
    "array<string>": "VARCHAR[]",
    "array<long>": "BIGINT[]",
}


def _map_iceberg_type(iceberg_type: str | None, field_name: str) -> str:
    """Map an iceberg_type string to a DuckLake sql_type string. Raises on unmapped."""
    if iceberg_type is None:
        raise ValueError(f"field {field_name!r}: iceberg_type is None -- cannot project sql_type")
    mapped = _ICEBERG_TO_SQL.get(iceberg_type)
    if mapped is None:
        raise ValueError(
            f"field {field_name!r}: iceberg_type {iceberg_type!r} has no sql_type mapping. "
            f"Add it to _ICEBERG_TO_SQL in scripts/schema_to_field_semantics.py (fail-closed)."
        )
    return mapped


def _project_role(derivation: dict[str, Any] | None) -> str:
    """Derive role from the derivation block: derived iff realized=True; input otherwise."""
    if derivation and derivation.get("realized") is True:
        return "derived"
    return "input"


def _enforce_migration_columns_subset(
    table_id: str,
    migration_columns: dict[str, Any],
    projected_columns: dict[str, Any],
) -> None:
    """Raise if any migration_columns entry is not a subset of projected_columns (rec-2232)."""
    for location in ("history", "current"):
        loc_entries = migration_columns.get(location, {})
        if not isinstance(loc_entries, dict):
            continue
        for col_name, col_spec in loc_entries.items():
            if col_name not in projected_columns:
                raise ValueError(
                    f"{table_id}: migration_columns[{location!r}][{col_name!r}] is not in "
                    f"the projected columns -- not a subset (rec-2232 enforcement)"
                )
            if not isinstance(col_spec, dict):
                continue
            proj = projected_columns[col_name]
            mig_sql = col_spec.get("sql_type")
            proj_sql = proj.get("sql_type")
            if mig_sql != proj_sql:
                raise ValueError(
                    f"{table_id}: migration_columns[{location!r}][{col_name!r}].sql_type "
                    f"mismatch: {mig_sql!r} vs projected {proj_sql!r} (rec-2232 type-consistency)"
                )


def _project_contract_table(
    table_id: str,
    resolved_fields: dict[str, Any],
    merge_key: str,
    ops_config: dict[str, Any],
    *,
    include_prose: bool = False,
) -> dict[str, Any]:
    """Project a Class A contract's resolved fields into an ops_tables entry."""
    history_table = f"{table_id}_history"
    current_table = f"{table_id}_current"
    partition: dict[str, str] = {
        "history": "day(created_timestamp)",
        "current": f"bucket(8, {merge_key})",
    }

    columns: dict[str, Any] = {}
    for fname, fspec in resolved_fields.items():
        derivation = fspec.derivation if hasattr(fspec, "derivation") else fspec.get("derivation")
        role = _project_role(derivation)
        sql_type = _map_iceberg_type(
            fspec.iceberg_type if hasattr(fspec, "iceberg_type") else fspec.get("iceberg_type"),
            fname,
        )
        nullable = fspec.nullable if hasattr(fspec, "nullable") else fspec.get("nullable")
        col: dict[str, Any] = {"role": role, "sql_type": sql_type, "nullable": nullable}
        if include_prose:
            desc = fspec.description if hasattr(fspec, "description") else fspec.get("description")
            sem = fspec.semantics if hasattr(fspec, "semantics") else fspec.get("semantics")
            if desc is not None:
                col["description"] = desc
            if sem is not None:
                col["semantics"] = sem
        columns[fname] = col

    migration_columns = ops_config.get("migration_columns")
    if migration_columns:
        _enforce_migration_columns_subset(table_id, migration_columns, columns)

    entry: dict[str, Any] = {
        "status": ops_config["status"],
        "merge_key": merge_key,
        "entity_id_prefix": ops_config["entity_id_prefix"],
        "id_keyspace": ops_config["id_keyspace"],
        "history_table": history_table,
        "current_table": current_table,
        "partition": partition,
        "columns": columns,
    }
    if migration_columns:
        entry["migration_columns"] = migration_columns
    return entry


def generate(*, include_prose: bool = False) -> dict[str, Any]:
    """Build the full field_semantics document from contracts + sidecar.

    include_prose=True adds description/semantics to each column entry (semantic slice).
    include_prose=False (default) emits only role/sql_type/nullable (mechanical slice).
    """
    from scripts.contracts import load_contract, resolve_refs

    sidecar = yaml.safe_load(_SIDECAR_PATH.read_text(encoding="utf-8"))

    doc: dict[str, Any] = {}
    for key in ("tables", "fields", "derivation_timing", "partition_transforms", "connection_settings"):
        doc[key] = sidecar[key]

    ops_tables: dict[str, Any] = {}
    contract_table_ops: dict[str, Any] = sidecar.get("contract_table_ops", {})

    for table_id in _CONTRACT_TABLE_IDS:
        contract_path = _CONTRACTS_DIR / f"{table_id}.yaml"
        contract_doc = load_contract(contract_path)

        merge_key = contract_doc.governance and contract_doc.governance.merge_key
        if not merge_key:
            raise ValueError(
                f"{table_id}: governance.merge_key is missing. "
                "Add merge_key to the top-level governance block in the contract before running the generator."
            )

        resolved = resolve_refs(contract_doc, _CONTRACTS_DIR)
        ops_config = contract_table_ops.get(table_id, {})
        ops_tables[table_id] = _project_contract_table(table_id, resolved, merge_key, ops_config, include_prose=include_prose)

    dormant = sidecar.get("dormant_ops_tables", {})
    for table_id in _DORMANT_TABLE_IDS:
        if table_id in dormant:
            ops_tables[table_id] = dormant[table_id]

    smoke = sidecar.get("smoke_ops_tables", {})
    for table_id in _SMOKE_TABLE_IDS:
        if table_id in smoke:
            ops_tables[table_id] = smoke[table_id]

    doc["ops_tables"] = ops_tables
    return doc


def _emit_yaml(doc: dict[str, Any]) -> str:
    """Emit the document as deterministic canonical YAML (header + block style, sorted=False)."""
    body = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
    return _GENERATED_HEADER + "\n" + body


def generate_mechanical_slice() -> str:
    """Emit only the mechanical projection (role/sql_type/nullable per column, no prose)."""
    doc = generate(include_prose=False)
    return _emit_yaml(doc)


def generate_semantic_slice() -> str:
    """Emit only description/semantics per column (semantic write-guidance surface)."""
    doc = generate(include_prose=True)
    ops = doc.get("ops_tables", {})
    semantic_ops: dict[str, Any] = {}
    for tbl, entry in ops.items():
        cols = entry.get("columns", {})
        semantic_cols: dict[str, Any] = {}
        for col, spec in cols.items():
            semantic_cols[col] = {k: v for k, v in spec.items() if k in ("description", "semantics") and v is not None}
        semantic_ops[tbl] = {"columns": semantic_cols}
    return yaml.dump({"ops_tables": semantic_ops}, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate config/lambda/ducklake/field_semantics.yaml from Class A contracts."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in-memory, byte-compare against committed file; exit non-zero on drift. "
        "Never writes (fail-closed, Decision 55).",
    )
    parser.add_argument(
        "--slice",
        choices=["mechanical", "semantic"],
        default=None,
        help="Emit only the named slice instead of the full document (stdout only).",
    )
    args = parser.parse_args(argv)

    if args.slice == "semantic":
        print(generate_semantic_slice(), end="")
        return 0

    generated = _emit_yaml(generate(include_prose=False))

    if args.slice == "mechanical":
        print(generated, end="")
        return 0

    if args.check:
        try:
            committed = _OUTPUT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot read committed file {_OUTPUT_PATH}: {exc}", file=sys.stderr)
            return 1
        try:
            rel = _OUTPUT_PATH.relative_to(ROOT)
        except ValueError:
            rel = _OUTPUT_PATH
        if generated == committed:
            print(f"OK: {rel} is up-to-date (no drift).")
            return 0
        print(
            f"DRIFT DETECTED: {rel} differs from the generator output.\n"
            "Run: bin/venv-python -m scripts.schema_to_field_semantics   (to regenerate)\n"
            "Do NOT hand-edit field_semantics.yaml -- it is GENERATED output.",
            file=sys.stderr,
        )
        return 1

    _OUTPUT_PATH.write_text(generated, encoding="utf-8")
    try:
        rel = _OUTPUT_PATH.relative_to(ROOT)
    except ValueError:
        rel = _OUTPUT_PATH
    print(f"Written: {rel}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
