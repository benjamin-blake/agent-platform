"""Reconcile-pending gate (hotfix follow-up to the 2026-07-24 ops_decisions incident).

One module, two entrypoints sharing one predicate:
  - validate_reconcile_pending_gate(failed): merge-time check, registered in BOTH validate.py
    tiers. Fails closed on an unclassified ops table; fails when a column added IN THE DIFF to
    a docs/contracts/ops_*.yaml contract OR a dormant_ops_tables/smoke_ops_tables columns: block
    lacks a matching pending_reconcile entry; fails when a pending_reconcile/reconciled entry
    names an undeclared column; fails when a current-side entry names an append_only table.
  - `--deploy-gate` CLI: exits non-zero while any reconcile_scope=ducklake table has a non-empty
    pending_reconcile. Invoked verbatim by deploy-ducklake-lambdas.yml's reconcile-gate job so
    the merge-time check and the deploy-time refusal can never drift apart.

Both entrypoints read _pending_reconcile_map() / _has_pending_reconcile() -- the SAME predicate
for "does this table have unresolved pending_reconcile columns" (two implementations of the same
predicate will drift, and the drifting one will be the deploy gate, because it runs least).

Static and zero-egress (Decision 88): reads only the sidecar YAML, the two Class A contracts, and
one _common diff -- never invokes ducklake_maintenance to introspect the live catalog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common, registry

_CONTRACTS_SUBDIR = Path("docs") / "contracts"
_SIDECAR_REL = Path("config") / "lambda" / "ducklake" / "field_semantics.static.yaml"
_VALID_SCOPES = ("ducklake", "exempt")


def _load_sidecar(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / _SIDECAR_REL).read_text(encoding="utf-8"))


def _ops_table_ids(root: Path) -> list[str]:
    """The authoritative table set: generate()['ops_tables'] keys -- NEVER contract_table_ops's
    own keys. A table missing its own contract_table_ops entry must fail closed, so the
    iteration source cannot be contract_table_ops itself (VP step 1 fix_if)."""
    root_str = str(root)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        import scripts.schema_to_field_semantics as _gen_mod

        doc = _gen_mod.generate(include_prose=False)
        return list(doc["ops_tables"].keys())
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def _declared_columns(table_id: str, sidecar: dict[str, Any], root: Path) -> set[str] | None:
    """Declared column-name set for table_id: Class A contract `fields` for the two contract
    tables; the sidecar's own dormant_ops_tables/smoke_ops_tables `columns:` block for the four
    non-contract tables. None if undeterminable."""
    contract_path = root / _CONTRACTS_SUBDIR / f"{table_id}.yaml"
    if contract_path.exists():
        contract_doc = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        return set((contract_doc or {}).get("fields", {}) or {})
    for block_name in ("dormant_ops_tables", "smoke_ops_tables"):
        block = sidecar.get(block_name, {}) or {}
        if table_id in block:
            return set((block[table_id].get("columns") or {}).keys())
    return None


def _write_mode(table_id: str, sidecar: dict[str, Any]) -> str:
    for block_name in ("dormant_ops_tables", "smoke_ops_tables"):
        block = sidecar.get(block_name, {}) or {}
        if table_id in block:
            return block[table_id].get("write_mode", "scd2")
    return "scd2"


def _pending_reconcile_map(sidecar: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Shared predicate input: {table_id: {'history': [...], 'current': [...]}}."""
    contract_table_ops = sidecar.get("contract_table_ops", {}) or {}
    out: dict[str, dict[str, list[str]]] = {}
    for table_id, ops_entry in contract_table_ops.items():
        pending = (ops_entry or {}).get("pending_reconcile") or {}
        out[table_id] = {
            "history": list(pending.get("history") or []),
            "current": list(pending.get("current") or []),
        }
    return out


def _has_pending_reconcile(pending: dict[str, list[str]]) -> bool:
    """THE shared predicate: does this table have any unresolved pending_reconcile column."""
    return bool(pending.get("history")) or bool(pending.get("current"))


def _blocking_tables(sidecar: dict[str, Any]) -> list[str]:
    """reconcile_scope=ducklake tables with a non-empty pending_reconcile -- what --deploy-gate refuses on."""
    contract_table_ops = sidecar.get("contract_table_ops", {}) or {}
    pending_map = _pending_reconcile_map(sidecar)
    blocking = [
        table_id
        for table_id, ops_entry in contract_table_ops.items()
        if (ops_entry or {}).get("reconcile_scope") == "ducklake" and _has_pending_reconcile(pending_map.get(table_id, {}))
    ]
    return sorted(blocking)


def _old_yaml(root: Path, rel_path: str) -> dict[str, Any] | None:
    result = _common.run(
        ["git", "show", f"origin/main:{rel_path}"], capture_output=True, text=True, encoding="utf-8", cwd=root
    )
    if result.returncode != 0:
        return None
    try:
        return yaml.safe_load(result.stdout)
    except yaml.YAMLError:
        return None


def _diff_added_columns(root: Path) -> dict[str, set[str]] | None:
    """Columns added IN THE DIFF (vs origin/main) to a contract or sidecar columns: block, keyed
    by table_id. Returns None (advisory) when origin/main is unreachable -- residual risk 1: a
    local session without a resolvable origin/main ref advisory-SKIPs this leg with a printed
    reason rather than false-greening (CI always resolves origin/main, so this hole is local-only)."""
    if not _common.origin_main_reachable(root):
        return None

    added: dict[str, set[str]] = {}

    for contract_path in sorted((root / _CONTRACTS_SUBDIR).glob("ops_*.yaml")):
        table_id = contract_path.stem
        new_doc = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        new_fields = set((new_doc or {}).get("fields", {}) or {})
        old_doc = _old_yaml(root, f"{_CONTRACTS_SUBDIR.as_posix()}/{contract_path.name}")
        old_fields = set((old_doc or {}).get("fields", {}) or {}) if old_doc is not None else set()
        newly_added = new_fields - old_fields
        if newly_added:
            added.setdefault(table_id, set()).update(newly_added)

    new_sidecar = _load_sidecar(root)
    old_sidecar = _old_yaml(root, _SIDECAR_REL.as_posix())
    for block_name in ("dormant_ops_tables", "smoke_ops_tables"):
        new_block = new_sidecar.get(block_name, {}) or {}
        old_block = ((old_sidecar or {}).get(block_name, {}) or {}) if old_sidecar is not None else {}
        for table_id, table_entry in new_block.items():
            new_cols = set((table_entry.get("columns") or {}).keys())
            old_cols = set(((old_block.get(table_id) or {}).get("columns") or {}).keys())
            newly_added = new_cols - old_cols
            if newly_added:
                added.setdefault(table_id, set()).update(newly_added)

    return added


def _check_unclassified_tables(table_ids: list[str], contract_table_ops: dict[str, Any], key: str, failed: list[str]) -> None:
    """Fail closed on an unclassified ops table (VP step 1 fix_if: iterate the AUTHORITATIVE
    table_ids, not contract_table_ops's own keys)."""
    for table_id in table_ids:
        ops_entry = contract_table_ops.get(table_id)
        scope = (ops_entry or {}).get("reconcile_scope")
        if scope not in _VALID_SCOPES:
            failed.append(
                f"{key} {table_id!r} has no valid reconcile_scope in contract_table_ops "
                f"(got {scope!r}, must be one of {_VALID_SCOPES}) -- an unclassified table must "
                "never silently pass the deploy gate."
            )


def _check_declared_columns_for_table(
    table_id: str,
    ops_entry: dict[str, Any] | None,
    declared: set[str] | None,
    write_mode: str,
    key: str,
    failed: list[str],
) -> None:
    """Undeclared-column + append_only-current checks for one table's pending_reconcile/reconciled."""
    for block_name in ("pending_reconcile", "reconciled"):
        block = (ops_entry or {}).get(block_name) or {}
        history_cols = list(block.get("history") or [])
        current_cols = list(block.get("current") or [])
        if declared is not None:
            for col in history_cols + current_cols:
                if col not in declared:
                    failed.append(
                        f"{key} {table_id!r} {block_name}[{col!r}] is not a declared column -- "
                        "not a subset of the Class A contract / sidecar columns: block."
                    )
        if current_cols and write_mode == "append_only":
            failed.append(
                f"{key} {table_id!r} {block_name}['current'] names column(s) {current_cols} but "
                "this table is write_mode append_only -- no current projection exists to reconcile."
            )


def _check_declared_columns(
    contract_table_ops: dict[str, Any], sidecar: dict[str, Any], root: Path, key: str, failed: list[str]
) -> None:
    """Undeclared-column + append_only-current checks over every declared table."""
    for table_id, ops_entry in contract_table_ops.items():
        declared = _declared_columns(table_id, sidecar, root)
        write_mode = _write_mode(table_id, sidecar)
        _check_declared_columns_for_table(table_id, ops_entry, declared, write_mode, key, failed)


def _check_diff_added_column_gap(root: Path, sidecar: dict[str, Any], key: str, failed: list[str]) -> None:
    """Diff-added column without a matching pending_reconcile entry -- the incident's actual
    failure mode: a column shipped in the deployed spec with no physical ALTER ever run."""
    added = _diff_added_columns(root)
    if added is None:
        print(
            "  ADVISORY-SKIP: origin/main is not resolvable locally -- diff-added-column leg skipped "
            "(residual risk 1; CI always resolves origin/main, so this hole is local-only)."
        )
        return

    pending_map = _pending_reconcile_map(sidecar)
    for table_id, new_cols in added.items():
        pending = pending_map.get(table_id, {"history": [], "current": []})
        write_mode = _write_mode(table_id, sidecar)
        required_sides = ["history"] if write_mode == "append_only" else ["history", "current"]
        for col in sorted(new_cols):
            for side in required_sides:
                if col not in pending.get(side, []):
                    failed.append(
                        f"{key} {table_id!r} column {col!r} was added in this diff but is absent from "
                        f"pending_reconcile[{side!r}] -- declare it in "
                        "config/lambda/ducklake/field_semantics.static.yaml's contract_table_ops before "
                        "merging, then run the admin-tier reconcile_columns action against the deployed "
                        "maintenance function to clear it after the maintenance deploy lands."
                    )


@registry.register("validate_reconcile_pending_gate", owner="platform")
def validate_reconcile_pending_gate(failed: list[str]) -> None:
    """Merge-time gate: static and zero-egress (Decision 88)."""
    print("\n=== Reconcile-pending gate (hotfix follow-up, 2026-07-24 ops_decisions incident) ===")
    root = _common.ROOT
    sidecar = _load_sidecar(root)
    contract_table_ops = sidecar.get("contract_table_ops", {}) or {}
    key = "reconcile-pending-gate:"

    try:
        table_ids = _ops_table_ids(root)
    except Exception as exc:  # noqa: BLE001
        failed.append(f"{key} could not resolve the ops table set via the generator: {exc}")
        return

    _check_unclassified_tables(table_ids, contract_table_ops, key, failed)
    _check_declared_columns(contract_table_ops, sidecar, root, key, failed)
    _check_diff_added_column_gap(root, sidecar, key, failed)

    if not any(f.startswith(key) for f in failed):
        print(f"  PASS: all {len(table_ids)} ops tables classified; no undeclared columns; no diff-added column gaps.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile-pending gate (merge-time check + deploy-time refusal).")
    parser.add_argument(
        "--deploy-gate",
        action="store_true",
        help="Exit non-zero while any reconcile_scope=ducklake table has a non-empty pending_reconcile.",
    )
    args = parser.parse_args(argv)

    if args.deploy_gate:
        sidecar = _load_sidecar(_common.ROOT)
        blocking = _blocking_tables(sidecar)
        if blocking:
            print(
                f"DEPLOY REFUSED: reconcile_scope=ducklake table(s) with a non-empty pending_reconcile: "
                f"{blocking}. The serving deploy (writer/reader/catalog-dr) is blocked until an operator "
                "runs the admin-tier reconcile_columns action against the deployed ducklake_maintenance "
                "function for each pending column, then clears pending_reconcile in "
                "config/lambda/ducklake/field_semantics.static.yaml (moving the column into `reconciled` "
                "with the response body as evidence).",
                file=sys.stderr,
            )
            return 1
        print("OK: no reconcile_scope=ducklake table has a pending reconcile.")
        return 0

    failed: list[str] = []
    validate_reconcile_pending_gate(failed)
    for f in failed:
        print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
