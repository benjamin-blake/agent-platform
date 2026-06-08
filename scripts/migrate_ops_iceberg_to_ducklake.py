# complexity-waiver: decision-43
"""One-time ops_* backfill: Iceberg current-state -> DuckLake SCD2 (T2.19 / Decision 81).

Reads every live Iceberg ops_* `current` row via DuckDBIcebergReader (the SOURCE is always Iceberg,
independent of OPS_STORAGE_BACKEND) and writes it into the DuckLake catalog via the generalized
runtime (src/common/ducklake_runtime). Then verifies parity (per-table row count + content hash of
the `current` projection) and LOUD-FAILS on any mismatch (Decision 55) -- a parity failure blocks the
cutover.

Decision 70: physically-deleted bootstrap rows (the dq_tombstones manifest) are EXCLUDED from the
backfill -- they must not be resurrected in DuckLake.

Idempotency by RE-CREATE, not append (resurrection-loop guard): a run DROPs + recreates each DuckLake
ops_* table before reloading, so a failed mid-sequence run never leaves a half-populated catalog that
a later run appends onto. This is the lakehouse anti-pattern guard -- the local Iceberg current-state
is the single source; we never restage from a stale cache.

Usage:
    # Dry-run: count source rows per table, no writes
    AWS_PROFILE=agent_platform bin/venv-python -m scripts.migrate_ops_iceberg_to_ducklake

    # Execute the backfill + verify parity (the [post-deploy] VP9 gate)
    AWS_PROFILE=agent_platform bin/venv-python -m scripts.migrate_ops_iceberg_to_ducklake --execute --verify-parity
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOMBSTONES_PATH = _REPO_ROOT / "config" / "agent" / "data_quality" / "dq_tombstones.yaml"

# The ops_* tables backfilled at cutover: ops_recommendations + ops_decisions ONLY -- the two LIVE
# cutover tables (file_rec/update_rec/file_decision/update_decision write paths).
# ops_priority_queue is EXCLUDED: its current-state is the Decision-70 latest-queue_run correlated set,
# NOT a per-merge-key MERGE, so a per-row backfill + read_current parity comparison would legitimately
# differ in row count and spuriously FAIL the cutover. It is dormant (executor paused, CD.17) with no
# live consumer; its backfill is deferred to executor-resume, when its snapshot semantics are handled.
# ops_session_log / ops_execution_plans are NOT provisioned in the personal account (sync_ops
# 2026-05-28 note) -- no source rows.
DEFAULT_TABLES = ("ops_recommendations", "ops_decisions")

_PROD_DATA_PATH_ENV = "DUCKLAKE_DATA_PATH"


class ParityError(RuntimeError):
    """Raised when Iceberg-vs-DuckLake parity fails. Loud-fail (Decision 55) -- blocks the cutover."""


def load_tombstone_ids(table: str, path: Path = _TOMBSTONES_PATH) -> set[str]:
    """Return the set of Decision-70 physically-deleted ids for *table* (excluded from the backfill)."""
    if not path.exists():
        return set()
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # pragma: no cover -- manifest read guard
        logger.warning("migrate: cannot read tombstones %s: %s", path, exc)
        return set()
    return {e.get("id", "") for e in spec.get("tombstones", []) if e.get("table") == table and e.get("id")}


def read_iceberg_current(table: str, reader: Any = None) -> list[dict]:
    """Read the Iceberg `current` rows for *table*. The SOURCE is ALWAYS Iceberg (not flag-selected)."""
    if reader is None:
        from src.common.iceberg_reader import DuckDBIcebergReader  # noqa: PLC0415

        reader = DuckDBIcebergReader()
    rows = reader.current_state(table)
    return [dict(r) for r in (rows or [])]


# Per-table coercion applied to BOTH sides before the parity hash, so the Iceberg side (raw
# DuckDBIcebergReader / Athena VarChar) and the DuckLake side (native list/int/bool) are normalized
# to identical Python types -- otherwise a `tags` value that is a string on one side and a list on
# the other hashes differently and triggers a spurious parity FAIL (Decision 55 / High #review).
def _normalize_rows(table: str, rows: list[dict]) -> list[dict]:
    """Apply the same sync_ops per-table coercion to *rows* so both backends compare type-for-type."""
    from scripts import sync_ops as _so  # noqa: PLC0415

    coercer = {
        "ops_recommendations": _so._coerce_ops_rec_row,
        "ops_decisions": _so._coerce_ops_decisions_row,
        "ops_priority_queue": _so._coerce_ops_priority_queue_row,
        "ops_session_log": _so._coerce_ops_session_log_row,
    }.get(table)
    if coercer is None:
        return [dict(r) for r in rows]
    out: list[dict] = []
    for r in rows:
        coerced = coercer(dict(r))
        if coerced is not None:  # _coerce_ops_rec_row returns None on an invalid id prefix
            out.append(coerced)
    return out


def _project_record(table: str, row: dict) -> dict:
    """Project a row onto the DuckLake INPUT columns (drop derived + unknown keys)."""
    from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

    spec = resolve_table_spec(table)
    inputs = {name for name, fspec in spec.fields.items() if fspec.get("role") == "input"}
    return {k: v for k, v in row.items() if k in inputs and v is not None}


def _content_hash(table: str, rows: list[dict]) -> str:
    """Stable content hash of the normalized input-column projection of *rows*, sorted by merge key.

    Both backends' rows are run through the same `_normalize_rows` coercion FIRST so type asymmetry
    (Athena VarChar vs DuckLake native) does not produce a spurious mismatch. Derived SCD2 envelope
    fields (ulid/created/last_updated) are excluded -- minted fresh by the runtime, different by
    construction, must not enter the parity comparison.
    """
    from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

    spec = resolve_table_spec(table)
    projected = [_project_record(table, r) for r in _normalize_rows(table, rows)]
    projected.sort(key=lambda r: str(r.get(spec.merge_key, "")))
    canonical = json.dumps(projected, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def backfill_table(
    table: str,
    *,
    con: Any,
    reader: Any = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Backfill one ops_* table from Iceberg into DuckLake. Returns a stats dict.

    DROP+recreate the DuckLake table pair (resurrection-loop guard), then write each non-tombstoned
    Iceberg current row through the generalized runtime. dry-run (execute=False) only counts.
    """
    from src.common import ducklake_runtime as rt  # noqa: PLC0415

    tombstones = load_tombstone_ids(table)
    spec = rt.resolve_table_spec(table)
    source_rows = read_iceberg_current(table, reader=reader)
    kept = [r for r in source_rows if str(r.get(spec.merge_key, "")) not in tombstones]
    excluded = len(source_rows) - len(kept)

    if not execute:
        return {
            "table": table,
            "source_rows": len(source_rows),
            "excluded_tombstones": excluded,
            "written": 0,
            "executed": False,
        }

    # Resurrection-loop guard: DROP + recreate before reloading (never append onto a partial catalog).
    rt.create_scd2_tables(con, table=table, force_recreate=True)
    written = 0
    for row in kept:
        rt.write_scd2(con, _project_record(table, row), table=table)
        written += 1
    return {
        "table": table,
        "source_rows": len(source_rows),
        "excluded_tombstones": excluded,
        "written": written,
        "executed": True,
    }


def verify_parity(table: str, *, con: Any, reader: Any = None) -> dict[str, Any]:
    """Compare Iceberg-vs-DuckLake `current` row count + content hash. Loud-fail on mismatch.

    Excludes Decision-70 tombstones from the Iceberg side (they were not backfilled). Returns a stats
    dict with parity='PASS'; raises ParityError otherwise.
    """
    from src.common import ducklake_runtime as rt  # noqa: PLC0415

    spec = rt.resolve_table_spec(table)
    tombstones = load_tombstone_ids(table)

    iceberg_rows = [r for r in read_iceberg_current(table, reader=reader) if str(r.get(spec.merge_key, "")) not in tombstones]
    ducklake_rows = rt.read_current(con, table=table)

    ice_n, dl_n = len(iceberg_rows), len(ducklake_rows)
    if ice_n != dl_n:
        raise ParityError(
            f"parity FAIL for {table}: Iceberg current={ice_n} rows but DuckLake current={dl_n} rows "
            "(excl. D70 tombstones). STOP + RCA (Decision 55) -- do not proceed with the cutover."
        )
    ice_hash = _content_hash(table, iceberg_rows)
    dl_hash = _content_hash(table, ducklake_rows)
    if ice_hash != dl_hash:
        raise ParityError(
            f"parity FAIL for {table}: row counts match ({ice_n}) but content hash differs "
            f"(iceberg={ice_hash[:12]} ducklake={dl_hash[:12]}). STOP + RCA (Decision 55)."
        )
    return {"table": table, "rows": ice_n, "content_hash": ice_hash[:12], "parity": "PASS"}


def _open_ducklake_connection() -> Any:
    """Open a runtime connection to the PRODUCTION DuckLake data path (admin/break-glass backfill)."""
    from src.common import ducklake_runtime as rt  # noqa: PLC0415

    data_path = os.environ.get(_PROD_DATA_PATH_ENV)
    if not data_path:
        raise RuntimeError(
            f"{_PROD_DATA_PATH_ENV} must be set to the production DuckLake data path for the backfill "
            "(the smoke path is the wrong target). Export it before running with --execute."
        )
    dsn = rt.fetch_dsn()
    # Dev/admin context: network INSTALL (extension_directory=None), production data_path.
    return rt.open_connection(dsn=dsn, data_path=data_path, extension_directory=None)


def run_migration(
    tables: tuple[str, ...] = DEFAULT_TABLES,
    *,
    execute: bool = False,
    verify: bool = False,
    connection_factory: Optional[Callable[[], Any]] = None,
    reader: Any = None,
) -> dict[str, Any]:
    """Backfill + (optionally) verify parity across *tables*. Returns an aggregate stats dict."""
    con = None
    if execute or verify:
        con = (connection_factory or _open_ducklake_connection)()
    try:
        backfill = [backfill_table(t, con=con, reader=reader, execute=execute) for t in tables]
        parity = [verify_parity(t, con=con, reader=reader) for t in tables] if verify else []
    finally:
        if con is not None:
            con.close()
    return {"backfill": backfill, "parity": parity, "verified": verify, "executed": execute}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="One-time Iceberg -> DuckLake ops_* backfill (T2.19).")
    parser.add_argument(
        "--execute", action="store_true", help="Perform the backfill (DROP+recreate+reload). Omit for dry-run."
    )
    parser.add_argument(
        "--verify-parity", action="store_true", dest="verify", help="Verify per-table row count + content-hash parity."
    )
    parser.add_argument(
        "--tables", nargs="*", default=list(DEFAULT_TABLES), help="Tables to migrate (default: the provisioned ops_* set)."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = run_migration(tuple(args.tables), execute=args.execute, verify=args.verify)
    except ParityError as exc:
        print(f"PARITY FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    if args.verify and all(p.get("parity") == "PASS" for p in result["parity"]):
        print("parity=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
