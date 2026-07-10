"""Direct TCP/5432 gates for the DuckLake Neon smoke-test suite (T2.16b / CD.34).

ATTACH round-trip, the connection-churn / OCC-collision gate, and the pg_dump -> scratch Neon ->
read-your-write restore drill. All three require outbound TCP/5432 and are refused from CC-web
(DIRECT_GATE_REFUSED, Decision 55) unless DUCKLAKE_ALLOW_DIRECT_GATE is set on a privileged host.
"""

from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from uuid import uuid4

from scripts.ducklake_smoke import core
from src.common import catalog_dr as _catalog_dr
from src.common import ducklake_runtime, ducklake_spike
from src.common.ducklake_runtime import (
    CHURN_WRITERS,
    CHURN_WRITES_PER_WRITER,
    COMMIT_LATENCY_BUDGET_MS,
    OCC_COLLISION_RATE_BUDGET,
)


def _open_attached(
    dsn: dict[str, str],
    *,
    profile: str | None = None,
    data_path: str = core.SMOKE_DATA_PATH,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> Any:
    """Open a DuckDB connection with the Neon catalog ATTACHed, delegating to ducklake_runtime.

    One ATTACH implementation (ducklake_runtime.open_connection) backs both the dev/smoke path (here,
    dev-mode network INSTALL: extension_directory=None) and the Lambda path (baked layer). The churn
    gate shares a single credential resolution across workers via _creds. Smoke uses the isolated
    ducklake_smoke meta-schema (rec-2099).
    """
    return ducklake_runtime.open_connection(
        dsn=dsn, data_path=data_path, meta_schema=core.META_SCHEMA, extension_directory=None, profile=profile, _creds=_creds
    )


def attach_roundtrip(*, profile: str | None = None, dsn: dict[str, str] | None = None) -> int:
    """ATTACH the catalog and SELECT 1; return the number of rows (1 on success). The V3 proof."""
    dsn = dsn or core.fetch_dsn(profile=profile)
    con = _open_attached(dsn, profile=profile)
    try:
        rows = con.execute("SELECT 1").fetchall()
        return len(rows)
    finally:
        con.close()


def _is_occ_collision(exc: Exception) -> bool:
    """Delegate to ducklake_runtime.is_occ_collision (single implementation -- rec-2091)."""
    return ducklake_runtime.is_occ_collision(exc)


def _single_writer_commit(
    writer_id: int,
    dsn: dict[str, str],
    *,
    profile: str | None = None,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> dict[str, Any]:
    """One churn iteration: a FRESH connection (connection-churn) + a contended write burst.

    Returns {"latency_ms": float, "collided": bool}. A non-OCC error propagates (a hard failure must
    not be silently counted as a collision).
    """
    start = time.perf_counter()
    collided = False
    con = _open_attached(dsn, profile=profile, _creds=_creds)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {core.CATALOG_ALIAS}.churn_probe (writer INTEGER, seq INTEGER)")
        for seq in range(CHURN_WRITES_PER_WRITER):
            try:
                con.execute(f"INSERT INTO {core.CATALOG_ALIAS}.churn_probe VALUES ({writer_id}, {seq})")
            except Exception as exc:  # noqa: BLE001 -- classify, then re-raise non-OCC
                if not _is_occ_collision(exc):
                    raise
                collided = True
    finally:
        con.close()
    return {"latency_ms": (time.perf_counter() - start) * 1000.0, "collided": collided}


def _run_churn_burst(
    dsn: dict[str, str],
    *,
    profile: str | None = None,
    writers: int = CHURN_WRITERS,
    worker: Callable[..., dict[str, Any]] = _single_writer_commit,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> list[dict[str, Any]]:
    """Run *writers* concurrent churn iterations and return their per-writer result dicts."""
    with ThreadPoolExecutor(max_workers=writers) as pool:
        futures = [pool.submit(worker, i, dsn, profile=profile, _creds=_creds) for i in range(writers)]
        return [f.result() for f in futures]


def _evaluate_churn(results: list[dict[str, Any]]) -> tuple[bool, dict[str, float]]:
    """Compute collision rate + p95 commit latency; return (passed, metrics) against the CD.33 budget."""
    total = len(results)
    collisions = sum(1 for r in results if r["collided"])
    collision_rate = (collisions / total) if total else 0.0
    p95_latency = core._p95([r["latency_ms"] for r in results])
    passed = collision_rate <= OCC_COLLISION_RATE_BUDGET and p95_latency <= COMMIT_LATENCY_BUDGET_MS
    return passed, {"collision_rate": collision_rate, "p95_latency_ms": p95_latency, "writers": float(total)}


def churn_gate(*, profile: str | None = None, dsn: dict[str, str] | None = None) -> dict[str, float]:
    """Run the connection-churn / OCC gate. Loud-fail (Decision 55) if outside CD.33's OCC budget."""
    if not os.environ.get("DUCKLAKE_ALLOW_DIRECT_GATE"):
        raise core.SmokeTestFailure(
            "DIRECT_GATE_REFUSED: --churn-gate requires outbound TCP/5432 which is blocked from CC-web. "
            "Canonical pre-deploy gate from CC-web: --canary-rehearsal (runs over 443 via Lambda). "
            "To force on a privileged host with TCP/5432 access: export DUCKLAKE_ALLOW_DIRECT_GATE=1"
        )
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    dsn = dsn or core.fetch_dsn(profile=profile)
    # Pre-warm: absorb Neon scale-to-zero cold-resume cost and pre-create the probe table
    # so concurrent writers only INSERT (avoids a concurrent-CREATE race on a fresh catalog).
    con = _open_attached(dsn, profile=profile)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {core.CATALOG_ALIAS}.churn_probe (writer INTEGER, seq INTEGER)")
    finally:
        con.close()
    # Pre-fetch credentials once so the 8 concurrent workers share a single STS assume-role
    # resolution instead of each making an independent call (8x parallel STS serializes badly).
    _session = boto3.Session(profile_name=resolve_aws_profile(profile))
    _fc = _session.get_credentials().get_frozen_credentials()
    _creds: tuple[str, str, str | None, str] = (_fc.access_key, _fc.secret_key, _fc.token, _session.region_name or "eu-west-2")
    results = _run_churn_burst(dsn, profile=profile, _creds=_creds)
    passed, metrics = _evaluate_churn(results)
    if not passed:
        raise core.SmokeTestFailure(
            "CHURN_GATE FAIL: collision_rate="
            f"{metrics['collision_rate']:.3f} (budget {OCC_COLLISION_RATE_BUDGET}), p95_latency_ms="
            f"{metrics['p95_latency_ms']:.1f} (budget {COMMIT_LATENCY_BUDGET_MS}). Implement an app-side "
            "pool and re-run -- do NOT relax the threshold (Decision 55)."
        )
    return metrics


def _engine_tag() -> str:
    """Engine-version tag for the dump filename: the pinned DuckDB version (drives restore compat)."""
    duckdb = ducklake_spike._require_duckdb()
    return f"duckdb-{getattr(duckdb, '__version__', 'unknown')}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing text output (utf-8, errors=replace). check=False -- callers inspect."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _dsn_uri(dsn: dict[str, str]) -> str:
    """Assemble a libpq URI for pg_dump/psql from DSN parts. Delegates to catalog_dr.dsn_uri (single impl)."""
    return _catalog_dr.dsn_uri(dsn)


def _consistent_pg_dump(dsn: dict[str, str], *, engine_tag: str, dump_path: str) -> str:
    """pg_dump the catalog with a single consistent snapshot (--serializable-deferrable). Loud-fail."""
    result = _run(["pg_dump", "--serializable-deferrable", "--no-owner", "--dbname", _dsn_uri(dsn), "--file", dump_path])
    if result.returncode != 0:
        err = result.stderr.strip()
        raise core.SmokeTestFailure(f"RESTORE_DRILL FAIL: pg_dump (tag {engine_tag}) rc={result.returncode}: {err}")
    return dump_path


def _restore_dump(dump_path: str, scratch_dsn: dict[str, str]) -> None:
    """Restore *dump_path* into the scratch Neon database via psql. Loud-fail on error."""
    result = _run(["psql", "--dbname", _dsn_uri(scratch_dsn), "--set", "ON_ERROR_STOP=1", "--file", dump_path])
    if result.returncode != 0:
        raise core.SmokeTestFailure(f"RESTORE_DRILL FAIL: psql restore rc={result.returncode}: {result.stderr.strip()}")


def _write_probe(dsn: dict[str, str], probe: str, *, profile: str | None = None) -> None:
    """Write a known read-your-write probe row into the catalog before the dump."""
    con = _open_attached(dsn, profile=profile)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {core.CATALOG_ALIAS}.restore_probe (token VARCHAR)")
        con.execute(f"INSERT INTO {core.CATALOG_ALIAS}.restore_probe VALUES ('{probe}')")
    finally:
        con.close()


def _verify_probe(scratch_dsn: dict[str, str], probe: str, *, profile: str | None = None) -> bool:
    """ATTACH the restored scratch catalog and confirm the probe row survived (read-your-write)."""
    con = _open_attached(scratch_dsn, profile=profile)
    try:
        rows = con.execute(f"SELECT token FROM {core.CATALOG_ALIAS}.restore_probe WHERE token = '{probe}'").fetchall()
        return len(rows) == 1
    finally:
        con.close()


def _derive_scratch_dsn(dsn: dict[str, str]) -> dict[str, str]:
    """Default scratch target: the same host with a _restore_drill database suffix (operator may override)."""
    scratch = dict(dsn)
    scratch["dbname"] = f"{dsn['dbname']}_restore_drill"
    return scratch


def restore_drill(
    *,
    profile: str | None = None,
    dsn: dict[str, str] | None = None,
    scratch_dsn: dict[str, str] | None = None,
    dump_path: str = "/tmp/ducklake_neon_restore_drill.sql",
) -> bool:
    """Consistent pg_dump -> scratch Neon -> DuckDB read-your-write. Loud-fail if the probe is lost."""
    if not os.environ.get("DUCKLAKE_ALLOW_DIRECT_GATE"):
        raise core.SmokeTestFailure(
            "DIRECT_GATE_REFUSED: --restore-drill requires outbound TCP/5432 which is blocked from CC-web. "
            "Canonical pre-deploy gate from CC-web: --canary-rehearsal (runs over 443 via Lambda). "
            "To force on a privileged host with TCP/5432 access: export DUCKLAKE_ALLOW_DIRECT_GATE=1"
        )
    dsn = dsn or core.fetch_dsn(profile=profile)
    scratch = scratch_dsn or _derive_scratch_dsn(dsn)
    probe = uuid4().hex
    _write_probe(dsn, probe, profile=profile)
    _consistent_pg_dump(dsn, engine_tag=_engine_tag(), dump_path=dump_path)
    _restore_dump(dump_path, scratch)
    if not _verify_probe(scratch, probe, profile=profile):
        raise core.SmokeTestFailure("RESTORE_DRILL FAIL: read-your-write probe missing after restore -- dump not consistent.")
    return True
