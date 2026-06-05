#!/usr/bin/env python3
"""DuckLake Neon catalog smoke test (T2.16b / CD.34, pending).

Three live gates, run post-deploy from a network-permitted context (egress to the Neon endpoint AND,
for a fresh extension install, to extensions.duckdb.org):

  --attach        ATTACH the Neon catalog over TLS (sslmode=require, SNI) on the pinned DuckDB and run
                  SELECT 1 against the DIRECT (unpooled) endpoint. Prints `ATTACH OK rows=1`.
  --churn-gate    Connection-churn / OCC-collision gate: a concurrent-writer burst on the direct
                  endpoint against a scale-to-zero Neon compute. Pass = OCC-collision rate AND commit
                  latency (including cold-resume) within CD.33's OCC budget. Prints `CHURN_GATE PASS`.
  --restore-drill Consistent pg_dump (--serializable-deferrable, engine-version-tagged) -> scratch
                  Neon database -> DuckDB read-your-write. Prints `RESTORE_OK read-your-write verified`.
                  The DR proof, run before any production write.

Reuses src/common/ducklake_spike.py for the duckdb-require + S3-credential helpers and fetches the Neon
DSN JSON from Secrets Manager (Decision 37). The churn gate and the restore drill LOUD-FAIL (Decision
55): a failed gate raises SmokeTestFailure and is a stop-and-RCA signal -- never silently relax a
threshold or degrade to pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional
from uuid import uuid4

from src.common import ducklake_spike

DSN_SECRET_ID = "ducklake-neon-catalog-dsn"
SMOKE_DATA_PATH = "s3://agent-platform-data-lake/ducklake-neon-smoke/"
CATALOG_ALIAS = "ops_catalog"
META_SCHEMA = "ducklake_ops"

# CD.33 OCC budget the churn gate must fit within. The DuckLake runtime uses bounded OCC retry; the
# gate fails loud if observed collisions OR commit latency exceed these. Decision 55: these thresholds
# are a stop signal, never a knob to loosen so the gate passes.
OCC_COLLISION_RATE_BUDGET = 0.20  # max fraction of writer iterations that hit an OCC collision
COMMIT_LATENCY_BUDGET_MS = 2000.0  # max p95 commit latency incl. Neon cold-resume
CHURN_WRITERS = 8  # concurrent fresh-connection writers in the burst
CHURN_WRITES_PER_WRITER = 5

# Substrings of a Postgres/DuckLake error that indicate an optimistic-concurrency / serialization
# collision (the expected, retryable contention signal) rather than a hard failure.
_OCC_COLLISION_MARKERS = ("could not serialize", "deadlock detected", "concurrent update", "occ", "conflict")


class SmokeTestFailure(RuntimeError):
    """Raised when a hard gate fails. Loud-fail (Decision 55) -- the caller must stop and RCA."""


def fetch_dsn(secret_id: str = DSN_SECRET_ID, *, profile: str | None = None) -> dict[str, str]:
    """Fetch + parse the Neon DSN JSON from Secrets Manager (Decision 37 runtime-fetch).

    Returns a dict with at least host / dbname / username / password (sslmode optional, defaults to
    require). Raises RuntimeError if the secret is missing a required key.
    """
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    session = boto3.Session(profile_name=resolve_aws_profile(profile))
    client = session.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_id)
    payload = json.loads(resp["SecretString"])
    missing = [k for k in ("host", "dbname", "username", "password") if not payload.get(k)]
    if missing:
        raise RuntimeError(f"DSN secret {secret_id!r} is missing required keys: {missing}")
    return payload


def _libpq_conninfo(dsn: dict[str, str]) -> str:
    """Return a libpq keyword/value conninfo string for the DuckLake postgres backend.

    sslmode defaults to require so TLS is always enforced even if the secret omits it (the secret
    written by Terraform always sets it; this is defence in depth).
    """
    sslmode = dsn.get("sslmode") or "require"
    return f"dbname={dsn['dbname']} host={dsn['host']} user={dsn['username']} password={dsn['password']} sslmode={sslmode}"


def _open_attached(dsn: dict[str, str], *, profile: str | None = None, data_path: str = SMOKE_DATA_PATH) -> Any:
    """Open a DuckDB connection with ducklake/postgres/httpfs loaded and the Neon catalog ATTACHed.

    Reuses the spike's duckdb-require + S3-credential helpers (extension-load + ATTACH pattern). The
    ATTACH uses the DuckLake postgres data source with META_SCHEMA, over the DIRECT endpoint + TLS.
    """
    duckdb = ducklake_spike._require_duckdb()
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake")
    con.execute("INSTALL postgres; LOAD postgres")
    con.execute("INSTALL httpfs; LOAD httpfs")
    ducklake_spike._set_s3_credentials(con, profile=profile)
    conninfo = _libpq_conninfo(dsn)
    con.execute(
        f"ATTACH 'ducklake:postgres:{conninfo}' AS {CATALOG_ALIAS} (DATA_PATH '{data_path}', META_SCHEMA '{META_SCHEMA}')"
    )
    return con


def attach_roundtrip(*, profile: str | None = None, dsn: dict[str, str] | None = None) -> int:
    """ATTACH the catalog and SELECT 1; return the number of rows (1 on success). The V3 proof."""
    dsn = dsn or fetch_dsn(profile=profile)
    con = _open_attached(dsn, profile=profile)
    try:
        rows = con.execute("SELECT 1").fetchall()
        return len(rows)
    finally:
        con.close()


def _is_occ_collision(exc: Exception) -> bool:
    """True if *exc* looks like an optimistic-concurrency / serialization collision (retryable)."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _OCC_COLLISION_MARKERS)


def _single_writer_commit(writer_id: int, dsn: dict[str, str], *, profile: str | None = None) -> dict[str, Any]:
    """One churn iteration: a FRESH connection (connection-churn) + a contended write burst.

    Returns {"latency_ms": float, "collided": bool}. A non-OCC error propagates (a hard failure must
    not be silently counted as a collision).
    """
    start = time.perf_counter()
    collided = False
    con = _open_attached(dsn, profile=profile)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.churn_probe (writer INTEGER, seq INTEGER)")
        for seq in range(CHURN_WRITES_PER_WRITER):
            try:
                con.execute(f"INSERT INTO {CATALOG_ALIAS}.churn_probe VALUES ({writer_id}, {seq})")
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
) -> list[dict[str, Any]]:
    """Run *writers* concurrent churn iterations and return their per-writer result dicts."""
    with ThreadPoolExecutor(max_workers=writers) as pool:
        futures = [pool.submit(worker, i, dsn, profile=profile) for i in range(writers)]
        return [f.result() for f in futures]


def _p95(values: list[float]) -> float:
    """Return the p95 of *values* (nearest-rank). Empty -> 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def _evaluate_churn(results: list[dict[str, Any]]) -> tuple[bool, dict[str, float]]:
    """Compute collision rate + p95 commit latency; return (passed, metrics) against the CD.33 budget."""
    total = len(results)
    collisions = sum(1 for r in results if r["collided"])
    collision_rate = (collisions / total) if total else 0.0
    p95_latency = _p95([r["latency_ms"] for r in results])
    passed = collision_rate <= OCC_COLLISION_RATE_BUDGET and p95_latency <= COMMIT_LATENCY_BUDGET_MS
    return passed, {"collision_rate": collision_rate, "p95_latency_ms": p95_latency, "writers": float(total)}


def churn_gate(*, profile: str | None = None, dsn: dict[str, str] | None = None) -> dict[str, float]:
    """Run the connection-churn / OCC gate. Loud-fail (Decision 55) if outside CD.33's OCC budget."""
    dsn = dsn or fetch_dsn(profile=profile)
    results = _run_churn_burst(dsn, profile=profile)
    passed, metrics = _evaluate_churn(results)
    if not passed:
        raise SmokeTestFailure(
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
    """Assemble a libpq URI for pg_dump/psql from DSN parts (sslmode defaults to require)."""
    sslmode = dsn.get("sslmode") or "require"
    return f"postgresql://{dsn['username']}:{dsn['password']}@{dsn['host']}/{dsn['dbname']}?sslmode={sslmode}"


def _consistent_pg_dump(dsn: dict[str, str], *, engine_tag: str, dump_path: str) -> str:
    """pg_dump the catalog with a single consistent snapshot (--serializable-deferrable). Loud-fail."""
    result = _run(["pg_dump", "--serializable-deferrable", "--no-owner", "--dbname", _dsn_uri(dsn), "--file", dump_path])
    if result.returncode != 0:
        err = result.stderr.strip()
        raise SmokeTestFailure(f"RESTORE_DRILL FAIL: pg_dump (tag {engine_tag}) rc={result.returncode}: {err}")
    return dump_path


def _restore_dump(dump_path: str, scratch_dsn: dict[str, str]) -> None:
    """Restore *dump_path* into the scratch Neon database via psql. Loud-fail on error."""
    result = _run(["psql", "--dbname", _dsn_uri(scratch_dsn), "--set", "ON_ERROR_STOP=1", "--file", dump_path])
    if result.returncode != 0:
        raise SmokeTestFailure(f"RESTORE_DRILL FAIL: psql restore rc={result.returncode}: {result.stderr.strip()}")


def _write_probe(dsn: dict[str, str], probe: str, *, profile: str | None = None) -> None:
    """Write a known read-your-write probe row into the catalog before the dump."""
    con = _open_attached(dsn, profile=profile)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.restore_probe (token VARCHAR)")
        con.execute(f"INSERT INTO {CATALOG_ALIAS}.restore_probe VALUES ('{probe}')")
    finally:
        con.close()


def _verify_probe(scratch_dsn: dict[str, str], probe: str, *, profile: str | None = None) -> bool:
    """ATTACH the restored scratch catalog and confirm the probe row survived (read-your-write)."""
    con = _open_attached(scratch_dsn, profile=profile)
    try:
        rows = con.execute(f"SELECT token FROM {CATALOG_ALIAS}.restore_probe WHERE token = '{probe}'").fetchall()
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
    dsn = dsn or fetch_dsn(profile=profile)
    scratch = scratch_dsn or _derive_scratch_dsn(dsn)
    probe = uuid4().hex
    _write_probe(dsn, probe, profile=profile)
    _consistent_pg_dump(dsn, engine_tag=_engine_tag(), dump_path=dump_path)
    _restore_dump(dump_path, scratch)
    if not _verify_probe(scratch, probe, profile=profile):
        raise SmokeTestFailure("RESTORE_DRILL FAIL: read-your-write probe missing after restore -- dump not consistent.")
    return True


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code (0 ok; 1 on a loud-fail gate or usage error)."""
    parser = argparse.ArgumentParser(prog="ducklake_neon_smoke_test", description="DuckLake Neon catalog smoke test (T2.16b).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--attach", action="store_true", help="ATTACH + SELECT 1 over TLS")
    group.add_argument("--churn-gate", action="store_true", help="connection-churn / OCC gate (loud-fail)")
    group.add_argument("--restore-drill", action="store_true", help="pg_dump -> scratch Neon -> read-your-write")
    parser.add_argument("--profile", default=None, help="AWS profile override for Secrets Manager / S3 creds")
    args = parser.parse_args(argv)

    try:
        if args.attach:
            rows = attach_roundtrip(profile=args.profile)
            print(f"ATTACH OK rows={rows}")
        elif args.churn_gate:
            m = churn_gate(profile=args.profile)
            print(f"CHURN_GATE PASS collision_rate={m['collision_rate']:.3f} p95_latency_ms={m['p95_latency_ms']:.1f}")
        else:
            restore_drill(profile=args.profile)
            print("RESTORE_OK read-your-write verified")
    except SmokeTestFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
