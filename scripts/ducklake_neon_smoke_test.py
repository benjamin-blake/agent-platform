#!/usr/bin/env python3
# complexity-waiver: decision-43 -- smoke-test driver: 5 Lambda gates (writer, reader, maintenance,
# catalog-dr, hot-merge) plus live attach, churn, and restore-drill paths legitimately exceed 500 SLOC.
"""DuckLake Neon catalog smoke test (T2.16b / T2.18 FP-B / CD.34).

Live gates, run post-deploy from a network-permitted context (egress to the Neon endpoint AND,
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

from src.common import catalog_dr as _catalog_dr
from src.common import ducklake_runtime, ducklake_spike
from src.common.ducklake_runtime import (
    CHURN_WRITERS,
    CHURN_WRITES_PER_WRITER,
    COMMIT_LATENCY_BUDGET_MS,
    OCC_COLLISION_RATE_BUDGET,
)

DSN_SECRET_ID = "ducklake-neon-catalog-dsn"
# Single source of truth: the runtime owns the canonical smoke DATA_PATH. A divergent literal here
# re-introduces drift and can bind the shared catalog to the wrong path on direct pre-checks.
SMOKE_DATA_PATH = ducklake_runtime.SMOKE_DATA_PATH
CATALOG_ALIAS = "ops_catalog"
# Smoke runs in its OWN meta-schema (ducklake_smoke), isolated from the production ducklake_ops catalog
# so it can never pin a DATA_PATH on production again (rec-2099 root-cause fix).
META_SCHEMA = ducklake_runtime.SMOKE_META_SCHEMA

# Function-URL endpoints for the in-Lambda invoke gates (post-deploy). Resolved from env first, then
# terraform output. The URLs are AWS_IAM-protected (SigV4 required; unsigned -> 403).
WRITER_URL_ENV = "DUCKLAKE_WRITER_URL"
READER_URL_ENV = "DUCKLAKE_READER_URL"
MAINTENANCE_URL_ENV = "DUCKLAKE_MAINTENANCE_URL"
CATALOG_DR_URL_ENV = "DUCKLAKE_CATALOG_DR_URL"

# CD.33 OCC budget: re-exported from ducklake_runtime (single source -- rec-2091). Decision 55:
# these are stop signals, never knobs to loosen so the gate passes.


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
    gate shares a single credential resolution across workers via _creds. Smoke uses the isolated
    ducklake_smoke meta-schema (rec-2099).
    """
    return ducklake_runtime.open_connection(
        dsn=dsn, data_path=data_path, meta_schema=META_SCHEMA, extension_directory=None, profile=profile, _creds=_creds
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
    """Assemble a libpq URI for pg_dump/psql from DSN parts. Delegates to catalog_dr.dsn_uri (single impl)."""
    return _catalog_dr.dsn_uri(dsn)


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
    """Resolve the writer/reader/maintenance/catalog_dr Function URL from env, then terraform output. Loud-fail if absent."""
    _env_map = {
        "writer": WRITER_URL_ENV,
        "reader": READER_URL_ENV,
        "maintenance": MAINTENANCE_URL_ENV,
        "catalog_dr": CATALOG_DR_URL_ENV,
    }
    env_name = _env_map.get(role, f"DUCKLAKE_{role.upper()}_URL")
    url = os.environ.get(env_name)
    if url:
        return url.rstrip("/")
    output_name = f"ducklake_{role}_function_url"
    try:
        result = subprocess.run(
            ["terraform", "-chdir=terraform/personal", "output", "-raw", output_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
        raise SmokeTestFailure(
            f"INGRESS FAIL: unsigned={unsigned.status_code} (want 403) signed={signed.status_code} (want 200)"
        )
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
    if not (
        body.get("schema_reject") == "raised" and body.get("occ_exhaust") == "raised" and body.get("silent_drop") is False
    ):
        raise SmokeTestFailure(f"LOUDFAIL FAIL: {body}")
    print("LOUDFAIL OK schema_reject=raised occ_exhaust=raised silent_drop=false")


def lambda_churn(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC8: N concurrent invocation fan-out on the DIRECT endpoint; per-invocation wall p95 within CD.33 budget.

    Pre-warm phase: issues N concurrent attach_check invocations to bring N Lambda containers out
    of cold-start before the measured burst (cold-start ~18s is already captured by lambda_attach
    EC1; EC8 measures warm-container steady-state latency, the production model per CD.33 clause 3).
    Then issues ONE setup invocation (pre-creates tables) and fans out CHURN_WRITERS concurrent
    churn_single invocations, each running in its own warm Lambda container/vCPU.

    Gate term is per-invocation wall p95 (latency_ms) -- the same subject action_churn used.
    Switching to commit_ms would be an implicit Decision-55 relaxation; wall is the measure.
    """
    writer_url = _function_url("writer")

    # Pre-warm: N concurrent attach_check invocations bring N Lambda containers out of cold-start
    # before the measured burst. Errors in pre-warm propagate immediately via _ok_json.
    with ThreadPoolExecutor(max_workers=CHURN_WRITERS) as pool:
        warm_futures = [
            pool.submit(_sigv4_invoke, writer_url, {"action": "attach_check"}, profile=profile, region=region)
            for _ in range(CHURN_WRITERS)
        ]
        for f in warm_futures:
            _ok_json(f.result())

    _ok_json(_sigv4_invoke(writer_url, {"action": "churn_single", "setup": True}, profile=profile, region=region))

    with ThreadPoolExecutor(max_workers=CHURN_WRITERS) as pool:
        futures = [
            pool.submit(_sigv4_invoke, writer_url, {"action": "churn_single", "writer_id": i}, profile=profile, region=region)
            for i in range(CHURN_WRITERS)
        ]
        responses = [f.result() for f in futures]

    bodies = [_ok_json(resp) for resp in responses]

    collided_count = sum(1 for b in bodies if b.get("collided"))
    collision_rate = collided_count / len(bodies) if bodies else 0.0
    p95_wall = _p95([b.get("latency_ms", 0.0) for b in bodies])
    breakdown = {
        "p95_connect_ms": round(_p95([b.get("connect_ms", 0.0) for b in bodies]), 2),
        "p95_commit_ms": round(_p95([b.get("commit_ms", 0.0) for b in bodies]), 2),
        "p95_wall_ms": round(p95_wall, 2),
        "p95_cpu_ms": round(_p95([b.get("cpu_ms", 0.0) for b in bodies]), 2),
        "total_occ_retries": sum(b.get("occ_retries", 0) for b in bodies),
        "wall_cpu_ratio": round(
            sum(b.get("wall_ms", b.get("latency_ms", 0.0)) for b in bodies)
            / max(sum(b.get("cpu_ms", 0.0) for b in bodies), 0.001),
            2,
        ),
        "writers": len(bodies),
    }
    within = collision_rate <= OCC_COLLISION_RATE_BUDGET and p95_wall <= COMMIT_LATENCY_BUDGET_MS
    breakdown_str = (
        f"collision_rate={round(collision_rate, 3)} p95_commit_ms={round(p95_wall, 1)} "
        f"endpoint=direct within_budget={within} "
        f"p95_connect_ms={breakdown['p95_connect_ms']} "
        f"p95_commit_ms_detail={breakdown['p95_commit_ms']} "
        f"p95_cpu_ms={breakdown['p95_cpu_ms']} "
        f"wall_cpu_ratio={breakdown['wall_cpu_ratio']} "
        f"total_occ_retries={breakdown['total_occ_retries']}"
    )
    if not within:
        raise SmokeTestFailure(
            f"CHURN FAIL: {breakdown_str} -- over the "
            "CD.33 budget. RCA the latency (Decision 55) -- do NOT relax the budget constants."
        )
    print(f"CHURN OK {breakdown_str}")


def lambda_churn_incontainer(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """Opt-in diagnostic: in-container 8-thread burst via the legacy action_churn. NOT the EC8 gate.

    Posts {"action":"churn"} and prints the per-stage breakdown. A budget miss is informational
    only -- this path is preserved for regression analysis. The EC8 measurement subject is the
    fan-out via lambda_churn (Decision 82 / CD.33 clause 3).
    """
    body = _ok_json(_sigv4_invoke(_function_url("writer"), {"action": "churn"}, profile=profile, region=region))
    bd = body.get("breakdown", {})
    print(
        f"CHURN_INCONTAINER (diagnostic, not a gate) collision_rate={body.get('collision_rate', 'n/a')} "
        f"p95_wall_ms={body.get('p95_commit_ms', 'n/a')} "
        f"within_budget={body.get('within_budget', 'n/a')} "
        f"wall_cpu_ratio={bd.get('wall_cpu_ratio', 'n/a')} "
        f"p95_connect_ms={bd.get('p95_connect_ms', 'n/a')} "
        f"p95_cpu_ms={bd.get('p95_cpu_ms', 'n/a')} "
        f"total_occ_retries={bd.get('total_occ_retries', 'n/a')}"
    )


def lambda_reader(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC1/boundary: reader returns current rows; the read role cannot write (closed boundary)."""
    read_body = _ok_json(
        _sigv4_invoke(_function_url("reader"), {"action": "read_current", "limit": 5}, profile=profile, region=region)
    )
    probe = _ok_json(_sigv4_invoke(_function_url("reader"), {"action": "write_probe"}, profile=profile, region=region))
    if not (read_body.get("row_count", 0) >= 1 and probe.get("write_denied") is True):
        raise SmokeTestFailure(f"READER FAIL: read={read_body} write_probe={probe}")
    print(f"READER OK rows={read_body['row_count']} write_denied=true")


def lambda_maintenance_merge(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 VP9: write many small files to smoke tables, invoke merge, assert file count drops.

    Writes 5 small records to force multiple small Parquet files, then invokes action=merge.
    Asserts files_after_merge >= 1 and that the response is ok=True.
    """
    maint_url = _function_url("maintenance")
    writer_url = _function_url("writer")

    # Pre-create tables and write several records to generate multiple small files.
    _ok_json(
        _sigv4_invoke(writer_url, {"action": "create_tables", "force_recreate_tables": True}, profile=profile, region=region)
    )
    for i in range(5):
        _ok_json(
            _sigv4_invoke(
                writer_url,
                {"action": "write", "record": {"rec_id": f"maint-merge-{i}", "payload": f"v{i}"}},
                profile=profile,
                region=region,
            )
        )

    body = _ok_json(_sigv4_invoke(maint_url, {"action": "merge"}, profile=profile, region=region))
    if not body.get("ok"):
        raise SmokeTestFailure(f"MAINTENANCE_MERGE FAIL: {body}")
    files_before = body.get("files_before", 0)
    files_after_merge = body.get("files_after_merge", 0)
    if files_after_merge > files_before:
        raise SmokeTestFailure(
            f"MAINTENANCE_MERGE FAIL: files grew after merge files_before={files_before} files_after_merge={files_after_merge}"
        )
    print(
        f"MAINTENANCE_MERGE OK files_before={files_before} files_after_merge={files_after_merge} "
        f"elapsed_ms={body.get('elapsed_ms', 'n/a')}"
    )


def lambda_maintenance_gc(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 VP10: invoke weekly GC; assert S3 object count stable/lower and breaker NOT tripped.

    Invokes action=gc on the live maintenance Lambda. Asserts ok=True, breaker_tripped=False,
    and files_after <= files_before (or files_before == 0 when the smoke tables are empty).
    """
    maint_url = _function_url("maintenance")
    body = _ok_json(_sigv4_invoke(maint_url, {"action": "gc"}, profile=profile, region=region))
    if not body.get("ok"):
        raise SmokeTestFailure(f"MAINTENANCE_GC FAIL: {body}")
    breaker_stats = body.get("breaker_stats", {})
    if breaker_stats.get("breaker_tripped"):
        raise SmokeTestFailure(f"MAINTENANCE_GC FAIL: circuit breaker tripped unexpectedly: {body}")
    files_before = body.get("files_before", 0)
    files_after = body.get("files_after", 0)
    if files_before > 0 and files_after > files_before:
        raise SmokeTestFailure(
            f"MAINTENANCE_GC FAIL: files_after ({files_after}) > files_before ({files_before}) -- storage grew"
        )
    print(
        f"MAINTENANCE_GC OK files_before={files_before} files_after={files_after} "
        f"breaker_tripped=false snapshots_expired={body.get('snapshots_expired', 0)} "
        f"files_cleaned={body.get('files_cleaned', 0)} orphans_deleted={body.get('orphans_deleted', 0)}"
    )


def lambda_maintenance_breaker(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 VP11: forced-threshold circuit-breaker trip; assert loud-fail (5xx) and no deletion.

    Invokes action=breaker_probe. Expects a 500 response with breaker_tripped=True. The
    MaintenanceBreakerTrip metric must be emitted (asserted via the response payload, not
    CloudWatch alarm state -- the alarm-state transition is timing-dependent and has no action
    target in FP-A, so it is not the load-bearing assertion here per VP step 11).
    """
    maint_url = _function_url("maintenance")
    resp = _sigv4_invoke(maint_url, {"action": "breaker_probe"}, profile=profile, region=region)
    body = resp.json()
    if resp.status_code == 200 and body.get("breaker_tripped") is False:
        print(
            "MAINTENANCE_BREAKER OK (no deletable files during probe; breaker did not trip) "
            "-- metric not emitted (correct: nothing to delete)"
        )
        return
    if resp.status_code != 500:
        raise SmokeTestFailure(f"MAINTENANCE_BREAKER FAIL: expected 500 (breaker trip) but got {resp.status_code}: {body}")
    if not body.get("breaker_tripped"):
        raise SmokeTestFailure(f"MAINTENANCE_BREAKER FAIL: response lacks breaker_tripped=True: {body}")
    print(f"MAINTENANCE_BREAKER OK status=500 breaker_tripped=true error_type={body.get('error_type', 'n/a')}")


def lambda_catalog_dr(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 FP-B VP11: invoke the DR Lambda; assert dump object + engine-version tag + CatalogDumpSuccess metric.

    Invokes the ducklake_catalog_dr Lambda via its Function URL (AWS_IAM). Asserts:
    - Response ok=True (200)
    - s3_key present and contains expected engine-version tags (pg16 + duckdb 1.5.3)
    - bucket returned matches the configured DR bucket
    - dump_bytes > 0 (a real dump was produced)

    The CatalogDumpSuccess CloudWatch metric emission is asserted via the response body
    (the Lambda only returns ok=True after a successful metric emit). CloudWatch alarm state
    transition is timing-dependent and is NOT the load-bearing assertion here.
    """
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    dr_url = _function_url("catalog_dr")
    resp = _sigv4_invoke(dr_url, {}, profile=profile, region=region)
    body = _ok_json(resp)
    if not body.get("ok"):
        raise SmokeTestFailure(f"CATALOG_DR FAIL: Lambda returned ok=False: {body}")

    s3_key = body.get("s3_key", "")
    bucket = body.get("bucket", "")
    dump_bytes = body.get("dump_bytes", 0)

    if "pg16" not in s3_key and "pg-16" not in s3_key and _catalog_dr.PINNED_PG_VERSION not in s3_key:
        raise SmokeTestFailure(f"CATALOG_DR FAIL: s3_key missing PG16 engine tag: {s3_key!r}")
    if ducklake_runtime.PINNED_DUCKDB_VERSION not in s3_key:
        raise SmokeTestFailure(
            f"CATALOG_DR FAIL: s3_key missing duckdb {ducklake_runtime.PINNED_DUCKDB_VERSION} tag: {s3_key!r}"
        )
    if not bucket:
        raise SmokeTestFailure(f"CATALOG_DR FAIL: no bucket in response: {body}")
    if dump_bytes <= 0:
        raise SmokeTestFailure(f"CATALOG_DR FAIL: dump_bytes={dump_bytes} (expected > 0)")

    # Confirm the object actually landed in S3 (belt-and-suspenders; the response already says ok).
    session = boto3.Session(profile_name=resolve_aws_profile(profile), region_name=region)
    s3 = session.client("s3")
    try:
        obj_meta = s3.head_object(Bucket=bucket, Key=s3_key)
        metadata = obj_meta.get("Metadata", {})
        if metadata.get("pg_version") != _catalog_dr.PINNED_PG_VERSION:
            raise SmokeTestFailure(
                f"CATALOG_DR FAIL: S3 object metadata pg_version={metadata.get('pg_version')!r} "
                f"(expected {_catalog_dr.PINNED_PG_VERSION!r})"
            )
        if metadata.get("duckdb_version") != ducklake_runtime.PINNED_DUCKDB_VERSION:
            raise SmokeTestFailure(
                f"CATALOG_DR FAIL: S3 object metadata duckdb_version={metadata.get('duckdb_version')!r} "
                f"(expected {ducklake_runtime.PINNED_DUCKDB_VERSION!r})"
            )
    except s3.exceptions.ClientError as exc:
        raise SmokeTestFailure(f"CATALOG_DR FAIL: S3 head_object failed: {exc}") from exc

    print(
        f"CATALOG_DR OK ok=true bucket={bucket} s3_key={s3_key} "
        f"dump_bytes={dump_bytes} pg_version={_catalog_dr.PINNED_PG_VERSION} "
        f"duckdb_version={ducklake_runtime.PINNED_DUCKDB_VERSION}"
    )


def lambda_maintenance_hot_merge(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 FP-B VP12: invoke hot_merge; assert files merged, nothing deleted (merge-only gate).

    Invokes action=hot_merge on the live maintenance Lambda. Asserts:
    - Response ok=True (200)
    - action == "hot_merge"
    - files_after <= files_before (merge can only reduce or hold file count)
    - No cleanup_old_files / delete_orphaned_files / expire_snapshots issued (merge-only invariant).

    The merge-only invariant is proven by the response body -- if the handler issued any
    destructive call, the Lambda would have returned ok=False or a 5xx (DuckLakeMaintenanceError).
    We additionally assert the action field is "hot_merge" and not "gc".
    """
    maint_url = _function_url("maintenance")
    body = _ok_json(_sigv4_invoke(maint_url, {"action": "hot_merge"}, profile=profile, region=region))
    if not body.get("ok"):
        raise SmokeTestFailure(f"MAINTENANCE_HOT_MERGE FAIL: {body}")
    if body.get("action") != "hot_merge":
        raise SmokeTestFailure(f"MAINTENANCE_HOT_MERGE FAIL: unexpected action in response: {body}")
    files_before = body.get("files_before", 0)
    files_after = body.get("files_after", 0)
    if files_after > files_before:
        raise SmokeTestFailure(
            f"MAINTENANCE_HOT_MERGE FAIL: files grew after hot_merge files_before={files_before} files_after={files_after}"
        )
    print(
        f"MAINTENANCE_HOT_MERGE OK files_before={files_before} files_after={files_after} "
        f"elapsed_ms={body.get('elapsed_ms', 'n/a')}"
    )


def ops_read_your_write(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.19 VP11: write via the writer (write_ops) -> read via the reader (read_ops_current).

    Proves the closed boundary end-to-end on the real ops schema: a write_ops lands and read_ops_current
    returns it; an update_ops is reflected; an update_ops on an ABSENT key loud-fails 409 (referential,
    CD.33 cl.8). Uses a `test-` probe id so the production counter is untouched.
    """
    writer_url = _function_url("writer")
    reader_url = _function_url("reader")
    table = "ops_recommendations"
    probe_id = f"test-ryw-{uuid4().hex[:12]}"
    base = {
        "id": probe_id,
        "status": "open",
        "title": "ops read-your-write probe",
        "source": "manual",
        "effort": "XS",
        "priority": "Low",
        "risk": "low",
        # DQ-required NOT-NULL columns: populated so the probe row is data-quality-clean while it
        # persists (the writer has no delete verb -- postmortem-DELETE deferred). Without these the
        # probe trips the ops_recommendations not_null DQ checks and reds the verifier harness.
        "automatable": False,
        "file": "scripts/ducklake_neon_smoke_test.py",
        "context": (
            "Read-your-write smoke probe written by ducklake_neon_smoke_test --ops-read-your-write "
            "to prove the closed DuckLake writer/reader boundary end-to-end on the real ops schema."
        ),
        "acceptance": "grep -q ops_read_your_write scripts/ducklake_neon_smoke_test.py",
    }
    _ok_json(
        _sigv4_invoke(writer_url, {"action": "write_ops", "table": table, "record": base}, profile=profile, region=region)
    )
    read1 = _ok_json(
        _sigv4_invoke(
            reader_url, {"action": "read_ops_current", "table": table, "key": probe_id}, profile=profile, region=region
        )
    )
    if read1.get("row_count") != 1 or read1["rows"][0].get("status") != "open":
        raise SmokeTestFailure(f"OPS_RYW FAIL: write_ops not read back: {read1}")

    updated = {**base, "status": "closed"}
    _ok_json(
        _sigv4_invoke(writer_url, {"action": "update_ops", "table": table, "record": updated}, profile=profile, region=region)
    )
    read2 = _ok_json(
        _sigv4_invoke(
            reader_url, {"action": "read_ops_current", "table": table, "key": probe_id}, profile=profile, region=region
        )
    )
    if read2["rows"][0].get("status") != "closed":
        raise SmokeTestFailure(f"OPS_RYW FAIL: update_ops not reflected: {read2}")

    absent = {**base, "id": f"test-absent-{uuid4().hex[:8]}", "status": "closed"}
    resp = _sigv4_invoke(
        writer_url, {"action": "update_ops", "table": table, "record": absent}, profile=profile, region=region
    )
    if resp.status_code != 409:
        raise SmokeTestFailure(
            f"OPS_RYW FAIL: update_ops on absent rec returned {resp.status_code} (expected 409 referential)"
        )
    print(f"OPS_RYW OK write+read+update reflected; absent-update referential=409 probe_id={probe_id}")


def ops_churn_regate(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.19 VP12: re-run the Decision-82 EC8 churn/OCC gate at production scope (post-cutover catalog).

    Delegates to the EC8 fan-out (CHURN_WRITERS=4, per-invocation wall p95<=2000ms, collision<=0.20 --
    the single-source budgets in ducklake_runtime). Production scope = the post-cutover production data
    path; the contention measured is catalog-commit-level (table-independent). Loud-fail on breach
    (Decision 55 -- never relax the budget to commit_ms).
    """
    lambda_churn(profile=profile, region=region)
    print("OPS_CHURN_REGATE OK (EC8 fan-out within CD.33 budget at production scope)")


def catalog_restore_drill(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.19 VP11: invoke the maintenance `restore_drill` action (pg_dump -> pg_restore + read-your-write).

    Lambda-mediated over 443 (there is NO Neon 5432 egress from CC-web): the maintenance Lambda runs the
    custom-format pg_dump -> pg_restore into a scratch meta-schema and verifies read-your-write INSIDE
    AWS, version-matched to the pinned engine. Loud-fail on a non-ok response (Decision 55).
    """
    maint_url = _function_url("maintenance")
    body = _ok_json(_sigv4_invoke(maint_url, {"action": "restore_drill"}, profile=profile, region=region))
    if not body.get("restored"):
        raise SmokeTestFailure(f"CATALOG_RESTORE_DRILL FAIL: maintenance restore_drill did not restore: {body}")
    print(
        f"CATALOG_RESTORE_DRILL OK maintenance restore_drill read-your-write verified "
        f"probe={body.get('probe_id')} pg={body.get('pg_version')}"
    )


def migrate_ops_recs_columns(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T1.13 VP step 8: invoke maintenance reconcile_columns SERVER-SIDE and assert context_v2_json is present.

    Uses the Lambda-mediated pattern (same as ops-read-your-write) because CC-web has no Neon 5432
    egress -- the DDL runs server-side inside the maintenance Lambda against the production catalog.
    Asserts the response reports context_v2_json present on BOTH history and current tables.
    Idempotent: a second run reports added_history=[] / added_current=[] (no-op).
    """
    import os  # noqa: PLC0415

    maint_url = _function_url("maintenance")
    data_path_env = os.environ.get("DUCKLAKE_DATA_PATH")
    try:
        tf_result = subprocess.run(
            ["terraform", "-chdir=terraform/personal", "output", "-raw", "ducklake_writer_data_path"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        tf_data_path = tf_result.stdout.strip() if tf_result.returncode == 0 else None
    except FileNotFoundError:
        tf_data_path = None

    data_path = data_path_env or tf_data_path or "s3://agent-platform-data-lake/ducklake/"
    payload = {
        "action": "reconcile_columns",
        "data_path": data_path,
        "meta_schema": "ducklake_ops",
        "table": "ops_recommendations",
    }
    body = _ok_json(_sigv4_invoke(maint_url, payload, profile=profile, region=region))
    if not body.get("ok"):
        raise SmokeTestFailure(f"MIGRATE_OPS_RECS_COLUMNS FAIL: maintenance reconcile_columns returned ok=False: {body}")
    added_h = body.get("added_history", [])
    added_c = body.get("added_current", [])
    pre_existing = body.get("columns_pre_existing", {})
    # After reconcile, context_v2_json must be present on both tables.
    # If the column was just added, it's in added_*. If it was already there, added_* is empty
    # but columns_pre_existing shows True (no-op run). Check both: newly added OR already present.
    history_ok = "context_v2_json" in added_h or pre_existing.get("history") is True
    current_ok = "context_v2_json" in added_c or pre_existing.get("current") is True
    if not history_ok or not current_ok:
        raise SmokeTestFailure(
            f"MIGRATE_OPS_RECS_COLUMNS FAIL: context_v2_json not confirmed on "
            f"history={history_ok} current={current_ok}. Response: {body}"
        )
    print(
        f"MIGRATE_OPS_RECS_COLUMNS OK context_v2_json present on history+current "
        f"added_history={added_h} added_current={added_c}"
    )


# NOTE: the seed_ops_recommendations payload emitter (emit_recs_seed_payload) and its
# --emit-recs-seed-payload flag were REMOVED at the 2026-06-09 recs sign-off alongside the maintenance
# seed action (closed boundary, Decision 81 cl.7). Re-seeding is now a break-glass operation: git-revert
# the removal commit (restores BOTH the maintenance action and this emitter), redeploy, re-seed, then
# re-remove. See docs/runbooks/ducklake-catalog-operations.md Section 6.


def connect_probe(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.19 RCA: SigV4-invoke the reader AND writer connect_probe actions; print the phased results.

    This is a diagnostic driver, NOT a pass/fail gate -- it reports the failing phase even on a
    diagnosed failure (ok=False). Both the reader and writer are probed so the failing phase is
    captured from the load-bearing read path (reader) AND the write path (writer).
    """
    reader_resp = _sigv4_invoke(_function_url("reader"), {"action": "connect_probe"}, profile=profile, region=region)
    writer_resp = _sigv4_invoke(_function_url("writer"), {"action": "connect_probe"}, profile=profile, region=region)
    reader_body = _ok_json(reader_resp)
    writer_body = _ok_json(writer_resp)
    print(
        f"CONNECT_PROBE reader=phase_reached:{reader_body.get('phase_reached')} "
        f"failed_phase:{reader_body.get('failed_phase')} ok:{reader_body.get('ok')} "
        f"dns_ms:{reader_body.get('dns_ms')} tcp_ms:{reader_body.get('tcp_ms')} "
        f"auth_ms:{reader_body.get('auth_ms')} attach_ms:{reader_body.get('attach_ms')} "
        f"error:{reader_body.get('error')!r}"
    )
    print(
        f"CONNECT_PROBE writer=phase_reached:{writer_body.get('phase_reached')} "
        f"failed_phase:{writer_body.get('failed_phase')} ok:{writer_body.get('ok')} "
        f"dns_ms:{writer_body.get('dns_ms')} tcp_ms:{writer_body.get('tcp_ms')} "
        f"auth_ms:{writer_body.get('auth_ms')} attach_ms:{writer_body.get('attach_ms')} "
        f"error:{writer_body.get('error')!r}"
    )


_LAMBDA_GATES: dict[str, Callable[..., None]] = {
    "lambda_attach": lambda_attach,
    "lambda_ingress": lambda_ingress,
    "lambda_idempotency": lambda_idempotency,
    "lambda_partition": lambda_partition,
    "lambda_inlining": lambda_inlining,
    "lambda_loudfail": lambda_loudfail,
    "lambda_churn": lambda_churn,
    "lambda_churn_incontainer": lambda_churn_incontainer,
    "lambda_reader": lambda_reader,
    "lambda_maintenance_merge": lambda_maintenance_merge,
    "lambda_maintenance_gc": lambda_maintenance_gc,
    "lambda_maintenance_breaker": lambda_maintenance_breaker,
    "lambda_catalog_dr": lambda_catalog_dr,
    "lambda_maintenance_hot_merge": lambda_maintenance_hot_merge,
    "connect_probe": connect_probe,
}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code (0 ok; 1 on a loud-fail gate or usage error)."""
    parser = argparse.ArgumentParser(
        prog="ducklake_neon_smoke_test", description="DuckLake Neon catalog smoke test (T2.16b / T2.17 / T2.18)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--attach", action="store_true", help="ATTACH + SELECT 1 over TLS")
    group.add_argument("--churn-gate", action="store_true", help="connection-churn / OCC gate (loud-fail)")
    group.add_argument("--restore-drill", action="store_true", help="pg_dump -> scratch Neon -> read-your-write")
    group.add_argument(
        "--ops-read-your-write",
        action="store_true",
        dest="ops_read_your_write",
        help="[post-deploy] T2.19 VP11: write_ops via writer -> read via reader; absent update loud-fails 409",
    )
    group.add_argument(
        "--ops-churn-regate",
        action="store_true",
        dest="ops_churn_regate",
        help="[post-deploy] T2.19 VP12: Decision-82 EC8 churn/OCC re-gate at production scope (loud-fail)",
    )
    group.add_argument(
        "--catalog-restore-drill",
        action="store_true",
        dest="catalog_restore_drill",
        help="[post-deploy] T2.19 VP11: invoke maintenance restore_drill (pg_dump->pg_restore + read-your-write)",
    )
    group.add_argument("--lambda-attach", action="store_true", help="[post-deploy] in-Lambda ATTACH proof (EC1)")
    group.add_argument(
        "--lambda-ingress", action="store_true", help="[post-deploy] AWS_IAM ingress unsigned=403/signed=200 (EC4)"
    )
    group.add_argument("--lambda-idempotency", action="store_true", help="[post-deploy] idempotent ULID append (EC10)")
    group.add_argument("--lambda-partition", action="store_true", help="[post-deploy] partition prune (EC6)")
    group.add_argument("--lambda-inlining", action="store_true", help="[post-deploy] inlining disabled (EC11)")
    group.add_argument("--lambda-loudfail", action="store_true", help="[post-deploy] schema/OCC loud-fail (EC7)")
    group.add_argument("--lambda-churn", action="store_true", help="[post-deploy] invocation fan-out churn/latency gate (EC8)")
    group.add_argument(
        "--lambda-churn-incontainer",
        action="store_true",
        help="[opt-in diagnostic] in-container 8-thread burst (legacy action_churn); NOT an EC8 gate",
    )
    group.add_argument("--lambda-reader", action="store_true", help="[post-deploy] closed reader path (EC1/boundary)")
    group.add_argument(
        "--lambda-maintenance-merge",
        action="store_true",
        help="[post-deploy] T2.18 daily merge gate: write small files, invoke merge, assert file count (VP9)",
    )
    group.add_argument(
        "--lambda-maintenance-gc",
        action="store_true",
        help="[post-deploy] T2.18 weekly GC gate: invoke GC, assert storage stable and breaker not tripped (VP10)",
    )
    group.add_argument(
        "--lambda-maintenance-breaker",
        action="store_true",
        help="[post-deploy] T2.18 breaker probe: forced-threshold trip, assert 5xx + breaker_tripped=True (VP11)",
    )
    group.add_argument(
        "--lambda-catalog-dr",
        action="store_true",
        help="[post-deploy] T2.18 FP-B DR gate: invoke DR Lambda, assert dump object + engine-version tag + metric (VP11)",
    )
    group.add_argument(
        "--lambda-maintenance-hot-merge",
        action="store_true",
        help="[post-deploy] T2.18 FP-B hot_merge gate: invoke hot_merge, assert files merged, nothing deleted (VP12)",
    )
    group.add_argument(
        "--connect-probe",
        action="store_true",
        dest="connect_probe",
        help="[post-deploy] T2.19 RCA: SigV4-invoke reader+writer connect_probe; print per-phase timings",
    )
    group.add_argument(
        "--migrate-ops-recs-columns",
        action="store_true",
        dest="migrate_ops_recs_columns",
        help="[post-deploy] T1.13 VP8: reconcile_columns SERVER-SIDE via maintenance Lambda; "
        "assert context_v2_json present on history+current (idempotent)",
    )
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
        elif args.ops_read_your_write:
            ops_read_your_write(profile=args.profile, region=args.region)
        elif args.migrate_ops_recs_columns:
            migrate_ops_recs_columns(profile=args.profile, region=args.region)
        elif args.ops_churn_regate:
            ops_churn_regate(profile=args.profile, region=args.region)
        elif args.catalog_restore_drill:
            catalog_restore_drill(profile=args.profile, region=args.region)
        elif args.connect_probe:
            connect_probe(profile=args.profile, region=args.region)
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
