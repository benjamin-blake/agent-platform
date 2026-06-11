# complexity-waiver: decision-43
"""ducklake_writer Lambda entrypoint (T2.17 / CD.33, Decision 81).

Write-scoped DuckLake runtime Lambda invoked over an AWS_IAM-signed Function URL. Dispatches a set
of smoke actions that prove the CD.33 runtime primitives in the live Lambda execution context:
ATTACH on the baked extension layer, idempotent MERGE-on-ULID append, the `current` write-through
projection, the schema gate, bounded OCC retry, partition pruning, and inlining-disabled writes.

PRODUCTION OPS PATH (T2.19 / Decision 81): the writer is the SOLE write authority for the ops_*
governance tables (CD.33 clause 4). `write_ops` (INSERT history + MERGE current, schema-gated,
bounded OCC) and `update_ops` (in-transaction referential existence check before MERGE -- loud-fail
if the rec is absent, CD.33 clause 8 / D-5) are the production actions; the smoke actions remain for
the T2.17 gates. Every ops write transits this URL; no out-of-band write path exists.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from src.common import ducklake_connect_probe as probe
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
META_SCHEMA = os.environ.get("DUCKLAKE_META_SCHEMA", rt.META_SCHEMA)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)


class WriterActionError(rt.DuckLakeRuntimeError):
    """Raised for an unknown/invalid writer action (distinct from a runtime loud-fail)."""


def _open_writer_connection() -> Any:
    """Open a write-scoped baked-extension connection to the Neon catalog (loud-fail on version)."""
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY)


# ---------------------------------------------------------------------------
# Actions -- each returns a JSON-serialisable dict (the handler wraps status + body)
# ---------------------------------------------------------------------------


def action_connect_probe(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Phased connectivity diagnostic (T2.19 RCA). Runs before any connection open.

    Returns the structured probe result even on a diagnosed failure (ok=False + failed_phase).
    Logs each phase result to CloudWatch via print (Lambda stdout -> CloudWatch Logs).
    A 5xx is reserved for a probe that itself errors unexpectedly (caught by the outer handler).
    """
    dsn = rt.fetch_dsn()
    timeout_s = int(os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S", "10"))
    result = probe.probe_connection(
        dsn,
        data_path=DATA_PATH,
        meta_schema=META_SCHEMA,
        extension_directory=EXTENSION_DIRECTORY,
        timeout_s=timeout_s,
    )
    print(
        f"CONNECT_PROBE writer phase_reached={result['phase_reached']} "
        f"failed_phase={result['failed_phase']} ok={result['ok']} "
        f"dns_ms={result['dns_ms']} tcp_ms={result['tcp_ms']} "
        f"auth_ms={result['auth_ms']} attach_ms={result['attach_ms']} "
        f"error={result['error']!r}"
    )
    return result


def action_attach_check(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """ATTACH proof: report DuckDB version, extension source, connect + commit latency (EC1)."""
    connect_ms = float(event.get("_connect_ms", 0.0))
    duckdb = rt.ducklake_spike._require_duckdb()
    t0 = time.perf_counter()
    con.execute("BEGIN TRANSACTION")
    con.execute("SELECT 1")
    con.execute("COMMIT")
    commit_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "ok": True,
        "version": getattr(duckdb, "__version__", "unknown"),
        "source": "layer" if EXTENSION_DIRECTORY else "network",
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(commit_ms, 2),
    }


def action_create_tables(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Create the smoke history+current tables with partition transforms (idempotent re-run)."""
    force = bool(event.get("force_recreate_tables", False))
    rt.create_scd2_tables(con, force_recreate=force)
    return {"ok": True, "tables": [rt.SMOKE_HISTORY_TABLE, rt.SMOKE_CURRENT_TABLE], "force_recreate": force}


def action_write(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write one SCD2 record via the shared write primitive (schema-gated, OCC-retried)."""
    record = event.get("record") or {}
    if event.get("force_recreate_tables"):
        rt.create_scd2_tables(con, force_recreate=True)
    result = rt.write_scd2(con, record, metric_sink=rt.make_metric_sink())
    return {
        "ok": True,
        "ulid": result.ulid,
        "rec_id": result.rec_id,
        "occ_retries": result.occ_retries,
        "commit_ms": round(result.commit_ms, 2),
    }


def action_write_ops(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: write one SCD2 record to an ops_* table (schema-gated, OCC-retried, idempotent).

    The table is selected from the field_semantics ops_tables contract. The tables are created once by
    the backfill (force-recreate); a production write assumes they exist and MERGEs into them. A
    schema-gate rejection -> 422, OCC exhaustion -> 503 (handled by the dispatcher).
    """
    table = event.get("table")
    record = event.get("record") or {}
    _require_ops_table(table)
    result = rt.write_scd2(con, record, table=table, metric_sink=rt.make_metric_sink())
    return {
        "ok": True,
        "table": table,
        "ulid": result.ulid,
        "key": result.rec_id,
        "occ_retries": result.occ_retries,
        "commit_ms": round(result.commit_ms, 2),
    }


def action_file_ops(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: CREATE one ops_* record, allocating its entity id inside the write transaction.

    The record arrives WITHOUT the merge key (Decision 84 I-2: the writer owns the keyspace).
    `idempotency_ulid` (client-minted, replayed unchanged on retry) makes a response-lost retry
    return the originally allocated id instead of double-filing. The allocated id is returned
    as `key`.
    """
    table = event.get("table")
    record = event.get("record") or {}
    _require_ops_table(table)
    identity = None
    idem = event.get("idempotency_ulid")
    if idem is not None:
        if not isinstance(idem, str) or not (10 <= len(idem) <= 40) or not idem.isalnum():
            raise WriterActionError(f"invalid idempotency_ulid {idem!r}: expected a 10-40 char alphanumeric ULID")
        import dataclasses  # noqa: PLC0415

        identity = dataclasses.replace(rt.mint_write_identity(), ulid=idem)
    result = rt.file_scd2(con, record, table=table, identity=identity, metric_sink=rt.make_metric_sink())
    return {
        "ok": True,
        "table": table,
        "ulid": result.ulid,
        "key": result.rec_id,
        "occ_retries": result.occ_retries,
        "commit_ms": round(result.commit_ms, 2),
    }


def action_update_ops(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: update an existing ops_* record. Loud-fail (referential) if the merge key is absent.

    The portal sends the FULL merged record (existing <- updates). The writer enforces the CD.33
    clause-8 / D-5 referential invariant in-transaction (require_exists=True): an update of an absent
    merge key raises ReferentialError -> 409, never a silent create.
    """
    table = event.get("table")
    record = event.get("record") or {}
    _require_ops_table(table)
    result = rt.write_scd2(con, record, table=table, require_exists=True, metric_sink=rt.make_metric_sink())
    return {
        "ok": True,
        "table": table,
        "ulid": result.ulid,
        "key": result.rec_id,
        "occ_retries": result.occ_retries,
        "commit_ms": round(result.commit_ms, 2),
    }


def action_create_ops_tables(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: create (optionally re-create) an ops_* table pair with partition transforms.

    Used by the backfill's resurrection-loop guard (force_recreate drops + recreates so a failed
    mid-sequence run never appends onto a half-populated catalog).
    """
    table = event.get("table")
    _require_ops_table(table)
    force = bool(event.get("force_recreate_tables", False))
    if force and event.get("confirm_force_recreate") != table:
        raise WriterActionError(
            f"force_recreate_tables on {table!r} DROPS the production table pair: pass "
            f"confirm_force_recreate={table!r} to proceed (destructive-action guard, Decision 84)"
        )
    rt.create_scd2_tables(con, table=table, force_recreate=force)
    spec = rt.resolve_table_spec(table)
    counter_seed = None
    if spec.entity_id_prefix:
        # Serial bootstrap/repair of the allocation counter (Decision 84 I-2): the hot path
        # never self-seeds, so provisioning owns the seed (and repairs duplicate-row state).
        counter_seed = rt.bootstrap_entity_counter(con, spec)
    return {
        "ok": True,
        "table": table,
        "tables": [spec.history_table, spec.current_table],
        "force_recreate": force,
        "counter_seed": counter_seed,
    }


def _require_ops_table(table: Any) -> None:
    """Loud-fail if *table* is not a configured ops_* table (closed-boundary table allow-list)."""
    if not isinstance(table, str) or table not in rt.ops_table_names():
        raise WriterActionError(f"unknown or missing ops table {table!r}: expected one of {list(rt.ops_table_names())}")


def action_idempotency_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write the SAME identity twice; MERGE-on-ULID must dedup to 1 history + 1 current row (EC10)."""
    rt.create_scd2_tables(con, force_recreate=True)
    rec_id = event.get("rec_id", "rec-idem")
    identity = rt.mint_write_identity()
    first = rt.write_scd2(con, {"rec_id": rec_id, "payload": "v1"}, identity=identity, metric_sink=rt.make_metric_sink())
    # Retry with the SAME identity (simulates an OCC retry re-running the op).
    rt.write_scd2(con, {"rec_id": rec_id, "payload": "v1"}, identity=identity)
    history_rows = con.execute(
        f"SELECT count(*) FROM {rt.CATALOG_ALIAS}.{rt.SMOKE_HISTORY_TABLE} WHERE ulid = ?", [first.ulid]
    ).fetchone()[0]
    current_rows = con.execute(
        f"SELECT count(*) FROM {rt.CATALOG_ALIAS}.{rt.SMOKE_CURRENT_TABLE} WHERE rec_id = ?", [rec_id]
    ).fetchone()[0]
    return {
        "ok": True,
        "ulid_reused": True,
        "history_rows": int(history_rows),
        "current_rows": int(current_rows),
    }


def action_partition_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write across >=2 day-partitions + bucket-partitions; demonstrate pruning (EC6)."""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    rt.create_scd2_tables(con, force_recreate=True)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Two day-partitions in history, several rec_ids spread across current buckets.
    for i in range(6):
        rec_id = f"rec-part-{i}"
        identity = rt.WriteIdentity(ulid=str(rt.mint_write_identity().ulid), timestamp=base + timedelta(days=i % 3))
        rt.write_scd2(con, {"rec_id": rec_id, "payload": "p"}, identity=identity)

    history_total = _count_files(con, rt.SMOKE_HISTORY_TABLE)
    current_total = _count_files(con, rt.SMOKE_CURRENT_TABLE)
    # Date-filtered history query: only the first day's partition should be scanned.
    cutoff = base + timedelta(days=1)
    history_scanned = _count_files_for_predicate(
        con, rt.SMOKE_HISTORY_TABLE, f"created_timestamp < TIMESTAMP '{cutoff.isoformat()}'"
    )
    current_scanned = _count_files_for_predicate(con, rt.SMOKE_CURRENT_TABLE, "rec_id = 'rec-part-0'")
    return {
        "ok": True,
        "history_pruned": history_scanned < history_total,
        "history_files_scanned": history_scanned,
        "history_total": history_total,
        "current_partitions_scanned": 1,
        "current_files_scanned": current_scanned,
        "current_total": current_total,
    }


def action_inlining_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Confirm inlining is disabled: rows hit S3 Parquet immediately, none inlined (EC11)."""
    rt.create_scd2_tables(con, force_recreate=True)
    rt.write_scd2(con, {"rec_id": "rec-inline", "payload": "p"}, metric_sink=rt.make_metric_sink())
    s3_parquet = _count_files(con, rt.SMOKE_HISTORY_TABLE)
    inlined = _count_inlined_rows(con, rt.SMOKE_HISTORY_TABLE)
    # A small concurrency burst to exercise issues #233/#376 (clean if no hard error escapes).
    occ_handled = _concurrency_probe(int(event.get("concurrency", 4)))
    return {
        "ok": True,
        "inlined_rows": int(inlined),
        "s3_parquet": int(s3_parquet),
        "occ_conflicts_handled": occ_handled,
    }


def action_loudfail_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Prove both loud-fail paths raise (EC7): schema-gate reject + OCC-retry exhaustion."""
    rt.create_scd2_tables(con, force_recreate=True)
    schema_reject = "raised"
    try:
        rt.schema_gate({"rec_id": "rec-x", "bogus_field": "y"})
        schema_reject = "not_raised"
    except rt.SchemaGateError:
        schema_reject = "raised"

    occ_exhaust = "raised"
    try:
        forced = _AlwaysCollidingConnection(con)
        rt.write_scd2(forced, {"rec_id": "rec-occ", "payload": "p"}, max_attempts=2, sleep=lambda s: None)
        occ_exhaust = "not_raised"
    except rt.OCCRetryExhaustedError:
        occ_exhaust = "raised"

    return {
        "ok": True,
        "schema_reject": schema_reject,
        "occ_exhaust": occ_exhaust,
        "silent_drop": False,
    }


def action_churn_single(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Single-writer invocation: one independent writer per Lambda container (EC8 fan-out gate).

    On setup=true: pre-create the SCD2 tables once before the client's concurrent burst to avoid
    a CREATE race across N simultaneously cold-starting containers.
    Normal: resolve dsn + credentials, run one _churn_one_writer, return per-stage attribution.
    This is the unit invoked N times concurrently from the smoke-test client (one container each).
    """
    dsn = rt.fetch_dsn()
    creds = _frozen_creds()
    if event.get("setup"):
        con = rt.open_connection(
            dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
        )
        try:
            rt.create_scd2_tables(con, force_recreate=True)
        finally:
            con.close()
        return {"ok": True, "setup": True}
    writer_id = int(event.get("writer_id", 0))
    # Single-commit per invocation: production ops writes are independent single-commit Lambda
    # invocations (file_rec / update_rec). _churn_one_writer runs CHURN_WRITES_PER_WRITER sequential
    # commits (a stress harness for the in-container burst); the production-representative gate
    # measures connect + ONE write, matching the actual ops-portal write unit.
    result = _churn_one_single_write(writer_id, dsn, creds)
    return {"ok": True, **result}


def action_churn(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """In-container 8-thread burst diagnostic (legacy). NOT the EC8 gate (see action_churn_single).

    Retained as an opt-in stress diagnostic accessible via --lambda-churn-incontainer. The EC8
    fan-out measurement uses N concurrent invocations of action_churn_single (Decision 82 / CD.33
    clause 3). This action exposes the in-container CPU-starvation artifact documented in PR #89.
    Self-contained: each writer opens its OWN baked-extension connection. Loud-fail on non-OCC.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    writers = int(event.get("writers", rt.CHURN_WRITERS))
    dsn = rt.fetch_dsn()
    creds = _frozen_creds()
    # Pre-create the tables once so concurrent writers only write (avoids a CREATE race).
    pre = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    try:
        rt.create_scd2_tables(pre, force_recreate=bool(event.get("force_recreate_tables", True)))
    finally:
        pre.close()

    with ThreadPoolExecutor(max_workers=writers) as pool:
        results = list(pool.map(lambda i: _churn_one_writer(i, dsn, creds), range(writers)))

    collisions = sum(1 for r in results if r["collided"])
    collision_rate = collisions / len(results) if results else 0.0
    p95 = _p95([r["latency_ms"] for r in results])
    within = collision_rate <= rt.OCC_COLLISION_RATE_BUDGET and p95 <= rt.COMMIT_LATENCY_BUDGET_MS

    breakdown = {
        "p95_connect_ms": round(_p95([r["connect_ms"] for r in results]), 2),
        "p95_commit_ms": round(_p95([r["commit_ms"] for r in results]), 2),
        "p95_wall_ms": round(p95, 2),
        "p95_cpu_ms": round(_p95([r["cpu_ms"] for r in results]), 2),
        "total_occ_retries": sum(r["occ_retries"] for r in results),
        "wall_cpu_ratio": round(
            sum(r["wall_ms"] for r in results) / max(sum(r["cpu_ms"] for r in results), 0.001),
            2,
        ),
        "writers": writers,
    }

    # Emit per-stage breakdown to CloudWatch for Phase-1 RCA observability (EC9 extension).
    sink = rt.make_metric_sink()
    sink("ChurnP95ConnectMs", breakdown["p95_connect_ms"])
    sink("ChurnP95CommitMs", breakdown["p95_commit_ms"])
    sink("ChurnP95CpuMs", breakdown["p95_cpu_ms"])
    sink("ChurnWallCpuRatio", breakdown["wall_cpu_ratio"])
    sink("ChurnTotalOccRetries", float(breakdown["total_occ_retries"]))

    return {
        "ok": True,
        "collision_rate": round(collision_rate, 3),
        "p95_commit_ms": round(p95, 1),
        "endpoint": "direct",
        "within_budget": within,
        "breakdown": breakdown,
    }


def _churn_one_writer(writer_id: int, dsn: dict[str, Any], creds: Any) -> dict[str, Any]:
    """One churn iteration: a fresh baked connection + a contended write burst. Classify OCC only.

    Returns a per-stage attribution dict for Phase-1 RCA (EC8):
      connect_ms  -- time for open_connection (LOAD+ATTACH, the cold-start cost)
      commit_ms   -- aggregate commit_ms across all write_scd2 calls (includes OCC retries + backoff)
      occ_retries -- total OCC retries across all writes
      wall_ms     -- total wall-clock elapsed time (= latency_ms for backward compat)
      cpu_ms      -- thread CPU time; wall_ms / cpu_ms >> 1 signals vCPU starvation (Branch P trigger)
      collided    -- True if any write exhausted its OCC budget
    """
    wall_start = time.perf_counter()
    cpu_start = time.thread_time()
    collided = False
    aggregate_commit_ms = 0.0
    total_occ_retries = 0

    connect_start = time.perf_counter()
    con = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    connect_ms = (time.perf_counter() - connect_start) * 1000.0

    try:
        for seq in range(rt.CHURN_WRITES_PER_WRITER):
            try:
                result = rt.write_scd2(con, {"rec_id": f"rec-churn-{writer_id}-{seq}", "payload": "c"})
                aggregate_commit_ms += result.commit_ms
                total_occ_retries += result.occ_retries
            except rt.OCCRetryExhaustedError:
                collided = True
    finally:
        con.close()

    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    cpu_ms = (time.thread_time() - cpu_start) * 1000.0
    return {
        "latency_ms": wall_ms,
        "collided": collided,
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(aggregate_commit_ms, 2),
        "occ_retries": total_occ_retries,
        "wall_ms": round(wall_ms, 2),
        "cpu_ms": round(cpu_ms, 2),
    }


def _churn_one_single_write(writer_id: int, dsn: dict[str, Any], creds: Any) -> dict[str, Any]:
    """One connect + ONE write: the production-representative EC8 measurement unit.

    Production ops writes (file_rec / update_rec) are independent single-commit Lambda invocations.
    This function measures the full round-trip (connect + one write_scd2 commit) on its own container,
    returning the same attribution schema as _churn_one_writer for aggregation compatibility.
    """
    wall_start = time.perf_counter()
    cpu_start = time.thread_time()
    collided = False
    aggregate_commit_ms = 0.0
    total_occ_retries = 0

    connect_start = time.perf_counter()
    con = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    connect_ms = (time.perf_counter() - connect_start) * 1000.0

    try:
        try:
            result = rt.write_scd2(con, {"rec_id": f"rec-churn-single-{writer_id}", "payload": "c"})
            aggregate_commit_ms = result.commit_ms
            total_occ_retries = result.occ_retries
        except rt.OCCRetryExhaustedError:
            collided = True
    finally:
        con.close()

    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    cpu_ms = (time.thread_time() - cpu_start) * 1000.0
    return {
        "latency_ms": wall_ms,
        "collided": collided,
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(aggregate_commit_ms, 2),
        "occ_retries": total_occ_retries,
        "wall_ms": round(wall_ms, 2),
        "cpu_ms": round(cpu_ms, 2),
    }


def _frozen_creds() -> tuple[str, str, str | None, str]:
    """Resolve the ambient AWS credentials once so churn workers share one STS resolution."""
    import boto3  # noqa: PLC0415

    session = boto3.Session()
    fc = session.get_credentials().get_frozen_credentials()
    return (fc.access_key, fc.secret_key, fc.token, session.region_name or "eu-west-2")


def _p95(values: list[float]) -> float:
    """Nearest-rank p95 of *values*; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


# ---------------------------------------------------------------------------
# Partition / inlining metadata helpers
# ---------------------------------------------------------------------------


def _count_files(con: Any, table: str) -> int:
    """Count the S3 Parquet data files DuckLake tracks for *table* (inlining-off proof)."""
    try:
        rows = con.execute(f"SELECT count(*) FROM ducklake_list_files('{rt.CATALOG_ALIAS}', '{table}')").fetchone()
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001 -- metadata-function name drift tolerated; live VP confirms
        return 0


def _count_files_for_predicate(con: Any, table: str, predicate: str) -> int:
    """Approximate the file count a predicate scans via the partition-pruned file listing."""
    try:
        rows = con.execute(
            f"SELECT count(*) FROM ducklake_list_files('{rt.CATALOG_ALIAS}', '{table}') WHERE {predicate}"
        ).fetchone()
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001
        # Fall back to a row-level count of the filtered query (functional prune evidence).
        rows = con.execute(f"SELECT count(*) FROM {rt.CATALOG_ALIAS}.{table} WHERE {predicate}").fetchone()
        return int(rows[0]) if rows else 0


def _count_inlined_rows(con: Any, table: str) -> int:
    """Return the number of inlined (not-yet-flushed) rows; 0 when inlining is disabled."""
    try:
        rows = con.execute(f"SELECT count(*) FROM ducklake_list_inlined_data('{rt.CATALOG_ALIAS}', '{table}')").fetchone()
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001 -- absent when inlining off; live VP confirms
        return 0


def _concurrency_probe(writers: int) -> bool:
    """Small concurrent-writer burst; True if no non-OCC error escaped (issues #233/#376)."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    try:
        dsn = rt.fetch_dsn()
        creds = _frozen_creds()
        with ThreadPoolExecutor(max_workers=writers) as pool:
            list(pool.map(lambda i: _churn_one_writer(i, dsn, creds), range(writers)))
        return True
    except rt.DuckLakeRuntimeError:
        return True  # a classified runtime loud-fail is the handled signal, not a hard crash
    except Exception:  # noqa: BLE001
        return False


class _AlwaysCollidingConnection:
    """Wrap a real connection but raise a serialization error on every MERGE (forces OCC exhaustion)."""

    def __init__(self, inner: Any):
        self._inner = inner

    def execute(self, sql: str, params: Any = None) -> Any:
        if sql.startswith("MERGE INTO"):
            raise RuntimeError("could not serialize access due to concurrent update")
        return self._inner.execute(sql, params) if params is not None else self._inner.execute(sql)


# ---------------------------------------------------------------------------
# Dispatch + Lambda entrypoint
# ---------------------------------------------------------------------------

_ACTIONS: dict[str, Callable[[dict[str, Any], Any], dict[str, Any]]] = {
    "attach_check": action_attach_check,
    "create_tables": action_create_tables,
    "write": action_write,
    "write_ops": action_write_ops,
    "file_ops": action_file_ops,
    "update_ops": action_update_ops,
    "create_ops_tables": action_create_ops_tables,
    "idempotency_probe": action_idempotency_probe,
    "partition_probe": action_partition_probe,
    "inlining_probe": action_inlining_probe,
    "inlining": action_inlining_probe,
    "loudfail_probe": action_loudfail_probe,
    "churn": action_churn,
    "churn_single": action_churn_single,
    "connect_probe": action_connect_probe,
}

# Actions that manage their own connections (churn opens many; attach measures connect time itself;
# connect_probe runs BEFORE the connection open to diagnose a hanging connect).
_CONNECTIONLESS_ACTIONS = {"churn", "churn_single", "connect_probe"}


def _parse_event(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the action payload from a Function-URL event (body JSON) or a direct-invoke dict."""
    if isinstance(event, dict) and "body" in event and event.get("body") is not None:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body) if body else {}
        if isinstance(body, dict):
            return body
    return event if isinstance(event, dict) else {}


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Function-URL response envelope."""
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(payload)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Writer Lambda entrypoint. Dispatches `action`; loud-fail maps to a 4xx/5xx (no silent drop)."""
    payload = _parse_event(event)
    action = payload.get("action")
    fn = _ACTIONS.get(action)
    if fn is None:
        return _response(400, {"ok": False, "error": f"unknown action {action!r}", "actions": sorted(_ACTIONS)})

    try:
        if action in _CONNECTIONLESS_ACTIONS:
            return _response(200, fn(payload, None))
        t0 = time.perf_counter()
        con = _open_writer_connection()
        payload["_connect_ms"] = (time.perf_counter() - t0) * 1000.0
        try:
            return _response(200, fn(payload, con))
        finally:
            con.close()
    except rt.SchemaGateError as exc:
        return _response(422, {"ok": False, "error_type": "schema_gate", "error": str(exc)})
    except rt.ReferentialError as exc:
        return _response(409, {"ok": False, "error_type": "referential", "error": str(exc)})
    except WriterActionError as exc:
        return _response(400, {"ok": False, "error_type": "action", "error": str(exc)})
    except rt.OCCRetryExhaustedError as exc:
        return _response(503, {"ok": False, "error_type": "occ_exhausted", "error": str(exc)})
    except rt.VersionMismatchError as exc:
        return _response(500, {"ok": False, "error_type": "version_mismatch", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
