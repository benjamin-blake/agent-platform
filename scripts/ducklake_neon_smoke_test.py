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
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional
from uuid import uuid4

from src.common import ducklake_runtime, ducklake_spike

DSN_SECRET_ID = "ducklake-neon-catalog-dsn"
SMOKE_DATA_PATH = "s3://agent-platform-data-lake/ducklake-neon-smoke/"
CATALOG_ALIAS = "ops_catalog"
META_SCHEMA = "ducklake_ops"

# Function-URL endpoints for the in-Lambda invoke gates (post-deploy). Resolved from env first, then
# terraform output. The two URLs are AWS_IAM-protected (SigV4 required; unsigned -> 403).
WRITER_URL_ENV = "DUCKLAKE_WRITER_URL"
READER_URL_ENV = "DUCKLAKE_READER_URL"

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


# DSN fetch + conninfo now live in ducklake_runtime (single implementation, no drift). Re-exported
# here so existing callers/tests keep the smoke-module entrypoints.
fetch_dsn = ducklake_runtime.fetch_dsn
_libpq_conninfo = ducklake_runtime.libpq_conninfo


def _open_attached(
    dsn: dict[str, str],
    *,
    profile: str | None = None,
    data_path: str = SMOKE_DATA_PATH,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> Any:
    """Open a DuckDB connection with the Neon catalog ATTACHed, delegating to ducklake_runtime.

    One ATTACH implementation (ducklake_runtime.open_connection) backs both the dev/smoke path (here,
    dev-mode network INSTALL: extension_directory=None) and the Lambda path (baked layer). The churn
    gate shares a single credential resolution across workers via _creds.
    """
    return ducklake_runtime.open_connection(
        dsn=dsn, data_path=data_path, extension_directory=None, profile=profile, _creds=_creds
    )


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
    _creds: tuple[str, str, str | None, str] | None = None,
) -> list[dict[str, Any]]:
    """Run *writers* concurrent churn iterations and return their per-writer result dicts."""
    with ThreadPoolExecutor(max_workers=writers) as pool:
        futures = [pool.submit(worker, i, dsn, profile=profile, _creds=_creds) for i in range(writers)]
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
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    dsn = dsn or fetch_dsn(profile=profile)
    # Pre-warm: absorb Neon scale-to-zero cold-resume cost and pre-create the probe table
    # so concurrent writers only INSERT (avoids a concurrent-CREATE race on a fresh catalog).
    con = _open_attached(dsn, profile=profile)
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.churn_probe (writer INTEGER, seq INTEGER)")
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


# ---------------------------------------------------------------------------
# In-Lambda invoke gates (post-deploy): SigV4-sign the AWS_IAM Function URLs.
# ---------------------------------------------------------------------------


def _function_url(role: str) -> str:
    """Resolve the writer/reader Function URL from env, then terraform output. Loud-fail if absent."""
    env_name = WRITER_URL_ENV if role == "writer" else READER_URL_ENV
    url = os.environ.get(env_name)
    if url:
        return url.rstrip("/")
    output_name = f"ducklake_{role}_function_url"
    try:
        result = subprocess.run(
            ["terraform", "-chdir=terraform/personal", "output", "-raw", output_name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().rstrip("/")
    except FileNotFoundError:
        pass
    raise SmokeTestFailure(
        f"{env_name} not set and terraform output {output_name!r} unavailable -- cannot reach the "
        f"{role} Function URL. Set {env_name} or run from a checkout with terraform state."
    )


def _sigv4_invoke(
    url: str, payload: dict[str, Any], *, profile: str | None = None, region: str = "eu-west-2", sign: bool = True
) -> Any:
    """POST *payload* (JSON) to a Lambda Function URL, optionally SigV4-signed (service 'lambda')."""
    import boto3  # noqa: PLC0415
    import requests  # noqa: PLC0415
    from botocore.auth import SigV4Auth  # noqa: PLC0415
    from botocore.awsrequest import AWSRequest  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    body = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if sign:
        session = boto3.Session(profile_name=resolve_aws_profile(profile))
        creds = session.get_credentials().get_frozen_credentials()
        aws_req = AWSRequest(method="POST", url=url, data=body, headers=dict(headers))
        SigV4Auth(creds, "lambda", region).add_auth(aws_req)
        headers = dict(aws_req.headers)
    return requests.post(url, data=body, headers=headers, timeout=180)


def _ok_json(resp: Any, *, expect: int = 200) -> dict[str, Any]:
    """Assert the Function-URL response status and return the parsed JSON body. Loud-fail otherwise."""
    if resp.status_code != expect:
        raise SmokeTestFailure(f"unexpected status {resp.status_code} (expected {expect}): {resp.text[:300]}")
    return resp.json()


def lambda_attach(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC1: ATTACH succeeds in-Lambda on baked extensions; report version + connect/commit latency."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "attach_check"}, profile=profile, region=region))
    if body.get("version") != ducklake_runtime.PINNED_DUCKDB_VERSION or body.get("source") != "layer":
        raise SmokeTestFailure(f"LAMBDA_ATTACH FAIL: {body}")
    print(
        f"LAMBDA_ATTACH OK version={body['version']} source={body['source']} "
        f"connect_ms={body['connect_ms']} commit_ms={body['commit_ms']}"
    )


def lambda_ingress(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC4: unsigned -> 403, SigV4 -> 200 (AWS_IAM ingress unaffected by the no-VPC config)."""
    url = _function_url("writer")
    unsigned = _sigv4_invoke(url, {"action": "attach_check"}, sign=False, profile=profile, region=region)
    signed = _sigv4_invoke(url, {"action": "attach_check"}, sign=True, profile=profile, region=region)
    if unsigned.status_code != 403 or signed.status_code != 200:
        raise SmokeTestFailure(f"INGRESS FAIL: unsigned={unsigned.status_code} (want 403) signed={signed.status_code} (want 200)")
    print("INGRESS OK unsigned=403 signed=200")


def lambda_idempotency(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC10: a retried write reuses its ULID; MERGE-on-ULID dedups to 1 history + 1 current row."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "idempotency_probe"}, profile=profile, region=region))
    if not (body.get("ulid_reused") and body.get("history_rows") == 1 and body.get("current_rows") == 1):
        raise SmokeTestFailure(f"IDEMPOTENCY FAIL: {body}")
    print(f"IDEMPOTENCY OK ulid_reused=true history_rows={body['history_rows']} current_rows={body['current_rows']}")


def lambda_partition(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC6: a date-filtered history query prunes partitions; the single-key current lookup is bounded."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "partition_probe"}, profile=profile, region=region))
    ok = (
        body.get("history_pruned")
        and body.get("history_files_scanned", 1) < body.get("history_total", 0)
        and body.get("current_partitions_scanned", 99) <= 1
        and body.get("current_files_scanned", 1) < body.get("current_total", 0)
    )
    if not ok:
        raise SmokeTestFailure(f"PARTITION FAIL: {body}")
    print(
        f"PARTITION OK history_pruned=true history_files_scanned={body['history_files_scanned']}"
        f"<{body['history_total']} current_partitions_scanned<=1 "
        f"current_files_scanned={body['current_files_scanned']}<{body['current_total']}"
    )


def lambda_inlining(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC11: inlining disabled -- inlined_rows=0, S3 Parquet present, concurrency probe clean."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "inlining_probe"}, profile=profile, region=region))
    if not (body.get("inlined_rows") == 0 and body.get("s3_parquet", 0) >= 1 and body.get("occ_conflicts_handled")):
        raise SmokeTestFailure(f"INLINING FAIL: {body}")
    print(f"INLINING OK inlined_rows=0 s3_parquet={body['s3_parquet']} occ_conflicts_handled=true")


def lambda_loudfail(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC7: schema-gate reject + OCC-retry exhaustion both raise loudly; no silent drop."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "loudfail_probe"}, profile=profile, region=region))
    if not (body.get("schema_reject") == "raised" and body.get("occ_exhaust") == "raised" and body.get("silent_drop") is False):
        raise SmokeTestFailure(f"LOUDFAIL FAIL: {body}")
    print("LOUDFAIL OK schema_reject=raised occ_exhaust=raised silent_drop=false")


def lambda_churn(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC8: in-region concurrent writers on the DIRECT endpoint; p95 within the CD.33 budget."""
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "churn"}, profile=profile, region=region))
    msg = (
        f"CHURN OK collision_rate={body['collision_rate']} p95_commit_ms={body['p95_commit_ms']} "
        f"endpoint={body['endpoint']}"
    )
    if not body.get("within_budget"):
        raise SmokeTestFailure(
            f"CHURN FAIL: collision_rate={body['collision_rate']} p95_commit_ms={body['p95_commit_ms']} over the "
            "CD.33 budget. RCA the latency (Decision 55) -- do NOT relax the budget constants."
        )
    print(msg)


def lambda_reader(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC1/boundary: reader returns current rows; the read role cannot write (closed boundary)."""
    read_body = _ok_json(_sigv4_invoke(_function_url("reader"), {"action": "read_current", "limit": 5}, profile=profile, region=region))
    probe = _ok_json(_sigv4_invoke(_function_url("reader"), {"action": "write_probe"}, profile=profile, region=region))
    if not (read_body.get("row_count", 0) >= 1 and probe.get("write_denied") is True):
        raise SmokeTestFailure(f"READER FAIL: read={read_body} write_probe={probe}")
    print(f"READER OK rows={read_body['row_count']} write_denied=true")


_LAMBDA_GATES: dict[str, Callable[..., None]] = {
    "lambda_attach": lambda_attach,
    "lambda_ingress": lambda_ingress,
    "lambda_idempotency": lambda_idempotency,
    "lambda_partition": lambda_partition,
    "lambda_inlining": lambda_inlining,
    "lambda_loudfail": lambda_loudfail,
    "lambda_churn": lambda_churn,
    "lambda_reader": lambda_reader,
}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code (0 ok; 1 on a loud-fail gate or usage error)."""
    parser = argparse.ArgumentParser(prog="ducklake_neon_smoke_test", description="DuckLake Neon catalog smoke test (T2.16b / T2.17).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--attach", action="store_true", help="ATTACH + SELECT 1 over TLS")
    group.add_argument("--churn-gate", action="store_true", help="connection-churn / OCC gate (loud-fail)")
    group.add_argument("--restore-drill", action="store_true", help="pg_dump -> scratch Neon -> read-your-write")
    group.add_argument("--lambda-attach", action="store_true", help="[post-deploy] in-Lambda ATTACH proof (EC1)")
    group.add_argument("--lambda-ingress", action="store_true", help="[post-deploy] AWS_IAM ingress unsigned=403/signed=200 (EC4)")
    group.add_argument("--lambda-idempotency", action="store_true", help="[post-deploy] idempotent ULID append (EC10)")
    group.add_argument("--lambda-partition", action="store_true", help="[post-deploy] partition prune (EC6)")
    group.add_argument("--lambda-inlining", action="store_true", help="[post-deploy] inlining disabled (EC11)")
    group.add_argument("--lambda-loudfail", action="store_true", help="[post-deploy] schema/OCC loud-fail (EC7)")
    group.add_argument("--lambda-churn", action="store_true", help="[post-deploy] in-region churn/latency (EC8)")
    group.add_argument("--lambda-reader", action="store_true", help="[post-deploy] closed reader path (EC1/boundary)")
    parser.add_argument("--profile", default=None, help="AWS profile override for Secrets Manager / S3 creds")
    parser.add_argument("--region", default="eu-west-2", help="AWS region for SigV4 / metrics")
    args = parser.parse_args(argv)

    try:
        if args.attach:
            rows = attach_roundtrip(profile=args.profile)
            print(f"ATTACH OK rows={rows}")
        elif args.churn_gate:
            m = churn_gate(profile=args.profile)
            print(f"CHURN_GATE PASS collision_rate={m['collision_rate']:.3f} p95_latency_ms={m['p95_latency_ms']:.1f}")
        elif args.restore_drill:
            restore_drill(profile=args.profile)
            print("RESTORE_OK read-your-write verified")
        else:
            gate = _selected_lambda_gate(args)
            gate(profile=args.profile, region=args.region)
    except SmokeTestFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _selected_lambda_gate(args: argparse.Namespace) -> Callable[..., None]:
    """Map the chosen --lambda-* flag to its gate function (resolved live so tests can patch it)."""
    for flag in _LAMBDA_GATES:
        if getattr(args, flag, False):
            return globals()[flag]
    raise SmokeTestFailure("no gate selected")  # pragma: no cover -- argparse mutually-exclusive guard


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
