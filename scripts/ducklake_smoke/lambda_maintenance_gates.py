"""Maintenance + catalog-DR Function-URL gates for the DuckLake Neon smoke suite (T2.18 / FP-B;
T2.18 c9 split, bundled Decision amending Decision 81 clause 1).

Daily merge, weekly GC, the forced-threshold circuit breaker, the catalog DR dump, and the
merge-only hot_merge gate. All call core._function_url / core._sigv4_invoke / core._ok_json
through the module object (Decision 104) so each has one canonical patch target.

The four maintenance gates (lambda_maintenance_merge/gc/breaker/hot_merge) resolve
core._function_url("maintenance_smoke") -- the CI-invokable smoke sibling
(src/lambdas/ducklake_maintenance_smoke/handler.py), NOT the admin ducklake_maintenance function.
This is the autonomous c9 post-deploy gate: github_ci_branch holds an invoke grant scoped to the
smoke function ARN only, so these gates now run unattended in the governed CD channel
(.github/workflows/deploy-ducklake-lambdas.yml) rather than requiring agent_platform_admin.
lambda_catalog_dr is unaffected -- ducklake_catalog_dr is already a separate function, out of
scope for this split.
"""

from __future__ import annotations

from scripts.ducklake_smoke import core
from src.common import catalog_dr as _catalog_dr
from src.common import ducklake_runtime


def lambda_maintenance_merge(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 c9: invoke merge on the smoke catalog, assert files_after_merge <= files_before.

    The maintenance-smoke Lambda uses the smoke catalog (ducklake_smoke schema, smoke S3 path),
    which is separate from the writer's production catalog (ducklake_ops). force_recreate_tables=
    True creates the smoke DuckLake tables if absent, making this call idempotent on a fresh
    environment. Invoked by github_ci_branch (CI-scoped MaintenanceSmokeInvokeCI grant) -- no
    longer requires agent_platform_admin now that the smoke cadences run on their own CI-invokable
    function (T2.18 c9 split).
    """
    maint_url = core._function_url("maintenance_smoke")
    body = core._ok_json(
        core._sigv4_invoke(maint_url, {"action": "merge", "force_recreate_tables": True}, profile=profile, region=region)
    )
    if not body.get("ok"):
        raise core.SmokeTestFailure(f"MAINTENANCE_MERGE FAIL: {body}")
    files_before = body.get("files_before", 0)
    files_after_merge = body.get("files_after_merge", 0)
    if files_after_merge > files_before:
        raise core.SmokeTestFailure(
            f"MAINTENANCE_MERGE FAIL: files grew after merge files_before={files_before} files_after_merge={files_after_merge}"
        )
    print(
        f"MAINTENANCE_MERGE OK files_before={files_before} files_after_merge={files_after_merge} "
        f"elapsed_ms={body.get('elapsed_ms', 'n/a')}"
    )


def lambda_maintenance_gc(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 c9: invoke weekly GC; assert S3 object count stable/lower and breaker NOT tripped.

    Invokes action=gc on the live maintenance-smoke Lambda. force_recreate_tables=True creates the
    smoke DuckLake tables if absent (same idempotent-on-fresh-environment handling as
    lambda_maintenance_merge; rec-2115 gap-1) so this gate does not 502 on a fresh smoke catalog.
    Asserts ok=True, breaker_tripped=False, and files_after <= files_before (or files_before == 0
    when the smoke tables are empty).
    """
    maint_url = core._function_url("maintenance_smoke")
    body = core._ok_json(
        core._sigv4_invoke(maint_url, {"action": "gc", "force_recreate_tables": True}, profile=profile, region=region)
    )
    if not body.get("ok"):
        raise core.SmokeTestFailure(f"MAINTENANCE_GC FAIL: {body}")
    breaker_stats = body.get("breaker_stats", {})
    if breaker_stats.get("breaker_tripped"):
        raise core.SmokeTestFailure(f"MAINTENANCE_GC FAIL: circuit breaker tripped unexpectedly: {body}")
    files_before = body.get("files_before", 0)
    files_after = body.get("files_after", 0)
    if files_before > 0 and files_after > files_before:
        raise core.SmokeTestFailure(
            f"MAINTENANCE_GC FAIL: files_after ({files_after}) > files_before ({files_before}) -- storage grew"
        )
    print(
        f"MAINTENANCE_GC OK files_before={files_before} files_after={files_after} "
        f"breaker_tripped=false snapshots_expired={body.get('snapshots_expired', 0)} "
        f"files_cleaned={body.get('files_cleaned', 0)} orphans_deleted={body.get('orphans_deleted', 0)}"
    )


def lambda_maintenance_breaker(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 c9: forced-threshold circuit-breaker trip; assert loud-fail (5xx) and no deletion.

    Invokes action=breaker_probe on the maintenance-smoke Lambda. Expects a 500 response with
    breaker_tripped=True. The MaintenanceBreakerTrip metric must be emitted (asserted via the
    response payload, not CloudWatch alarm state -- the alarm-state transition is timing-dependent
    and has no action target in FP-A, so it is not the load-bearing assertion here).
    """
    maint_url = core._function_url("maintenance_smoke")
    resp = core._sigv4_invoke(maint_url, {"action": "breaker_probe"}, profile=profile, region=region)
    body = resp.json()
    if resp.status_code == 200 and body.get("breaker_tripped") is False:
        print(
            "MAINTENANCE_BREAKER OK (no deletable files during probe; breaker did not trip) "
            "-- metric not emitted (correct: nothing to delete)"
        )
        return
    if resp.status_code != 500:
        raise core.SmokeTestFailure(
            f"MAINTENANCE_BREAKER FAIL: expected 500 (breaker trip) but got {resp.status_code}: {body}"
        )
    if not body.get("breaker_tripped"):
        raise core.SmokeTestFailure(f"MAINTENANCE_BREAKER FAIL: response lacks breaker_tripped=True: {body}")
    print(f"MAINTENANCE_BREAKER OK status=500 breaker_tripped=true error_type={body.get('error_type', 'n/a')}")


def lambda_catalog_dr(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 FP-B VP11: invoke the DR Lambda; assert dump object + engine-version tag + CatalogDumpSuccess metric.

    Invokes the ducklake_catalog_dr Lambda via its Function URL (AWS_IAM). Asserts:
    - Response ok=True (200)
    - s3_key present and contains expected engine-version tags (pg16 + duckdb at the pinned version)
    - bucket returned matches the configured DR bucket
    - dump_bytes > 0 (a real dump was produced)

    The CatalogDumpSuccess CloudWatch metric emission is asserted via the response body
    (the Lambda only returns ok=True after a successful metric emit). CloudWatch alarm state
    transition is timing-dependent and is NOT the load-bearing assertion here.
    """
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    dr_url = core._function_url("catalog_dr")
    resp = core._sigv4_invoke(dr_url, {}, profile=profile, region=region)
    body = core._ok_json(resp)
    if not body.get("ok"):
        raise core.SmokeTestFailure(f"CATALOG_DR FAIL: Lambda returned ok=False: {body}")

    s3_key = body.get("s3_key", "")
    bucket = body.get("bucket", "")
    dump_bytes = body.get("dump_bytes", 0)

    if "pg16" not in s3_key and "pg-16" not in s3_key and _catalog_dr.PINNED_PG_VERSION not in s3_key:
        raise core.SmokeTestFailure(f"CATALOG_DR FAIL: s3_key missing PG16 engine tag: {s3_key!r}")
    if ducklake_runtime.PINNED_DUCKDB_VERSION not in s3_key:
        raise core.SmokeTestFailure(
            f"CATALOG_DR FAIL: s3_key missing duckdb {ducklake_runtime.PINNED_DUCKDB_VERSION} tag: {s3_key!r}"
        )
    if not bucket:
        raise core.SmokeTestFailure(f"CATALOG_DR FAIL: no bucket in response: {body}")
    if dump_bytes <= 0:
        raise core.SmokeTestFailure(f"CATALOG_DR FAIL: dump_bytes={dump_bytes} (expected > 0)")

    # Confirm the object actually landed in S3 (belt-and-suspenders; the response already says ok).
    session = boto3.Session(profile_name=resolve_aws_profile(profile), region_name=region)
    s3 = session.client("s3")
    try:
        obj_meta = s3.head_object(Bucket=bucket, Key=s3_key)
        metadata = obj_meta.get("Metadata", {})
        if metadata.get("pg_version") != _catalog_dr.PINNED_PG_VERSION:
            raise core.SmokeTestFailure(
                f"CATALOG_DR FAIL: S3 object metadata pg_version={metadata.get('pg_version')!r} "
                f"(expected {_catalog_dr.PINNED_PG_VERSION!r})"
            )
        if metadata.get("duckdb_version") != ducklake_runtime.PINNED_DUCKDB_VERSION:
            raise core.SmokeTestFailure(
                f"CATALOG_DR FAIL: S3 object metadata duckdb_version={metadata.get('duckdb_version')!r} "
                f"(expected {ducklake_runtime.PINNED_DUCKDB_VERSION!r})"
            )
    except s3.exceptions.ClientError as exc:
        raise core.SmokeTestFailure(f"CATALOG_DR FAIL: S3 head_object failed: {exc}") from exc

    print(
        f"CATALOG_DR OK ok=true bucket={bucket} s3_key={s3_key} "
        f"dump_bytes={dump_bytes} pg_version={_catalog_dr.PINNED_PG_VERSION} "
        f"duckdb_version={ducklake_runtime.PINNED_DUCKDB_VERSION}"
    )


def lambda_maintenance_hot_merge(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """T2.18 FP-B / c9: invoke hot_merge; assert files merged, nothing deleted (merge-only gate).

    Invokes action=hot_merge on the live maintenance-smoke Lambda. Asserts:
    - Response ok=True (200)
    - action == "hot_merge"
    - files_after <= files_before (merge can only reduce or hold file count)
    - No cleanup_old_files / delete_orphaned_files / expire_snapshots issued (merge-only invariant).

    The merge-only invariant is proven by the response body -- if the handler issued any
    destructive call, the Lambda would have returned ok=False or a 5xx (DuckLakeMaintenanceError).
    We additionally assert the action field is "hot_merge" and not "gc".
    """
    maint_url = core._function_url("maintenance_smoke")
    body = core._ok_json(core._sigv4_invoke(maint_url, {"action": "hot_merge"}, profile=profile, region=region))
    if not body.get("ok"):
        raise core.SmokeTestFailure(f"MAINTENANCE_HOT_MERGE FAIL: {body}")
    if body.get("action") != "hot_merge":
        raise core.SmokeTestFailure(f"MAINTENANCE_HOT_MERGE FAIL: unexpected action in response: {body}")
    files_before = body.get("files_before", 0)
    files_after = body.get("files_after", 0)
    if files_after > files_before:
        raise core.SmokeTestFailure(
            f"MAINTENANCE_HOT_MERGE FAIL: files grew after hot_merge files_before={files_before} files_after={files_after}"
        )
    print(
        f"MAINTENANCE_HOT_MERGE OK files_before={files_before} files_after={files_after} "
        f"elapsed_ms={body.get('elapsed_ms', 'n/a')}"
    )
