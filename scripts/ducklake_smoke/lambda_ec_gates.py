"""Writer/reader EC + warm-reuse Function-URL gates for the DuckLake Neon smoke suite (T2.17 / D2).

In-Lambda invoke gates over the AWS_IAM Function URLs (post-deploy): attach, ingress, idempotency,
partition pruning, inlining, loud-fail, the EC8 churn/OCC fan-out (Decision 82), the closed reader
boundary, and warm-connection reuse (rec-2096). All call core._function_url / core._sigv4_invoke /
core._ok_json through the module object (Decision 104) so each has one canonical patch target.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from scripts.ducklake_smoke import core
from src.common import ducklake_runtime
from src.common.ducklake_runtime import CHURN_WRITERS, COMMIT_LATENCY_BUDGET_MS, OCC_COLLISION_RATE_BUDGET


def lambda_attach(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC1: ATTACH succeeds in-Lambda on baked extensions; report version + connect/commit latency."""
    body = core._ok_json(
        core._sigv4_invoke(core._function_url("writer"), {"action": "attach_check"}, profile=profile, region=region)
    )
    if body.get("version") != ducklake_runtime.PINNED_DUCKDB_VERSION or body.get("source") != "layer":
        raise core.SmokeTestFailure(f"LAMBDA_ATTACH FAIL: {body}")
    print(
        f"LAMBDA_ATTACH OK version={body['version']} source={body['source']} "
        f"connect_ms={body['connect_ms']} commit_ms={body['commit_ms']}"
    )


def lambda_ingress(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC4: unsigned -> 403, SigV4 -> 200 (AWS_IAM ingress unaffected by the no-VPC config)."""
    url = core._function_url("writer")
    unsigned = core._sigv4_invoke(url, {"action": "attach_check"}, sign=False, profile=profile, region=region)
    signed = core._sigv4_invoke(url, {"action": "attach_check"}, sign=True, profile=profile, region=region)
    if unsigned.status_code != 403 or signed.status_code != 200:
        raise core.SmokeTestFailure(
            f"INGRESS FAIL: unsigned={unsigned.status_code} (want 403) signed={signed.status_code} (want 200)"
        )
    print("INGRESS OK unsigned=403 signed=200")


def lambda_idempotency(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC10: a retried write reuses its ULID; MERGE-on-ULID dedups to 1 history + 1 current row."""
    body = core._ok_json(
        core._sigv4_invoke(core._function_url("writer"), {"action": "idempotency_probe"}, profile=profile, region=region)
    )
    if not (body.get("ulid_reused") and body.get("history_rows") == 1 and body.get("current_rows") == 1):
        raise core.SmokeTestFailure(f"IDEMPOTENCY FAIL: {body}")
    print(f"IDEMPOTENCY OK ulid_reused=true history_rows={body['history_rows']} current_rows={body['current_rows']}")


def lambda_partition(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC6: a date-filtered history query prunes partitions; the single-key current lookup is bounded."""
    body = core._ok_json(
        core._sigv4_invoke(core._function_url("writer"), {"action": "partition_probe"}, profile=profile, region=region)
    )
    ok = (
        body.get("history_pruned")
        and body.get("history_files_scanned", 1) < body.get("history_total", 0)
        and body.get("current_partitions_scanned", 99) <= 1
        and body.get("current_files_scanned", 1) < body.get("current_total", 0)
    )
    if not ok:
        raise core.SmokeTestFailure(f"PARTITION FAIL: {body}")
    print(
        f"PARTITION OK history_pruned=true history_files_scanned={body['history_files_scanned']}"
        f"<{body['history_total']} current_partitions_scanned<=1 "
        f"current_files_scanned={body['current_files_scanned']}<{body['current_total']}"
    )


def lambda_inlining(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC11: inlining disabled -- inlined_rows=0, S3 Parquet present, concurrency probe clean."""
    body = core._ok_json(
        core._sigv4_invoke(core._function_url("writer"), {"action": "inlining_probe"}, profile=profile, region=region)
    )
    if not (body.get("inlined_rows") == 0 and body.get("s3_parquet", 0) >= 1 and body.get("occ_conflicts_handled")):
        raise core.SmokeTestFailure(f"INLINING FAIL: {body}")
    print(f"INLINING OK inlined_rows=0 s3_parquet={body['s3_parquet']} occ_conflicts_handled=true")


def lambda_loudfail(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """EC7: schema-gate reject + OCC-retry exhaustion both raise loudly; no silent drop."""
    body = core._ok_json(
        core._sigv4_invoke(core._function_url("writer"), {"action": "loudfail_probe"}, profile=profile, region=region)
    )
    if not (
        body.get("schema_reject") == "raised" and body.get("occ_exhaust") == "raised" and body.get("silent_drop") is False
    ):
        raise core.SmokeTestFailure(f"LOUDFAIL FAIL: {body}")
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
    writer_url = core._function_url("writer")

    # Pre-warm: N concurrent attach_check invocations bring N Lambda containers out of cold-start
    # before the measured burst. Errors in pre-warm propagate immediately via _ok_json.
    with ThreadPoolExecutor(max_workers=CHURN_WRITERS) as pool:
        warm_futures = [
            pool.submit(core._sigv4_invoke, writer_url, {"action": "attach_check"}, profile=profile, region=region)
            for _ in range(CHURN_WRITERS)
        ]
        for f in warm_futures:
            core._ok_json(f.result())

    core._ok_json(core._sigv4_invoke(writer_url, {"action": "churn_single", "setup": True}, profile=profile, region=region))

    with ThreadPoolExecutor(max_workers=CHURN_WRITERS) as pool:
        futures = [
            pool.submit(
                core._sigv4_invoke, writer_url, {"action": "churn_single", "writer_id": i}, profile=profile, region=region
            )
            for i in range(CHURN_WRITERS)
        ]
        responses = [f.result() for f in futures]

    bodies = [core._ok_json(resp) for resp in responses]

    collided_count = sum(1 for b in bodies if b.get("collided"))
    collision_rate = collided_count / len(bodies) if bodies else 0.0
    p95_wall = core._p95([b.get("latency_ms", 0.0) for b in bodies])
    breakdown = {
        "p95_connect_ms": round(core._p95([b.get("connect_ms", 0.0) for b in bodies]), 2),
        "p95_commit_ms": round(core._p95([b.get("commit_ms", 0.0) for b in bodies]), 2),
        "p95_wall_ms": round(p95_wall, 2),
        "p95_cpu_ms": round(core._p95([b.get("cpu_ms", 0.0) for b in bodies]), 2),
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
        raise core.SmokeTestFailure(
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
    body = core._ok_json(core._sigv4_invoke(core._function_url("writer"), {"action": "churn"}, profile=profile, region=region))
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
    read_body = core._ok_json(
        core._sigv4_invoke(
            core._function_url("reader"), {"action": "read_current", "limit": 5}, profile=profile, region=region
        )
    )
    probe = core._ok_json(
        core._sigv4_invoke(core._function_url("reader"), {"action": "write_probe"}, profile=profile, region=region)
    )
    if not (read_body.get("row_count", 0) >= 1 and probe.get("write_denied") is True):
        raise core.SmokeTestFailure(f"READER FAIL: read={read_body} write_probe={probe}")
    print(f"READER OK rows={read_body['row_count']} write_denied=true")


def _warm_reuse_probe(role: str, *, profile: str | None, region: str, attempts: int = 6) -> dict:
    """Invoke `role`'s attach_check repeatedly until warm reuse is observed; then force a cold reconnect.

    Returns a structured result (neon-egress-reduction D2 / rec-2096): cold + warm connect latency, the
    observed reuse flag, and whether a post-reset invocation reconnects ok. Lambda routing across
    containers is non-deterministic, so reuse is polled (a low-concurrency sequential burst lands on
    the warm container within a few tries); the cold-reconnect check is deterministic (reset drops the
    warm slot on the container that serves the next invocation).
    """
    url = core._function_url(role)
    # Drop any pre-existing warm connection so the first sample is a genuine cold ATTACH.
    core._sigv4_invoke(url, {"action": "reset_warm_connection"}, profile=profile, region=region)
    cold = core._ok_json(core._sigv4_invoke(url, {"action": "attach_check"}, profile=profile, region=region))

    warm: dict | None = None
    for _ in range(attempts):
        body = core._ok_json(core._sigv4_invoke(url, {"action": "attach_check"}, profile=profile, region=region))
        if body.get("connect_reused"):
            warm = body
            break

    # Forced cold/dead-connection variant: drop the warm slot, then a fresh invocation must reconnect.
    core._sigv4_invoke(url, {"action": "reset_warm_connection"}, profile=profile, region=region)
    recold = core._ok_json(core._sigv4_invoke(url, {"action": "attach_check"}, profile=profile, region=region))

    return {
        "role": role,
        "cold_connect_ms": cold.get("connect_ms"),
        "warm_connect_ms": (warm or {}).get("connect_ms"),
        "warm_reuse_observed": warm is not None,
        "reconnect_ok": bool(recold.get("ok")),
    }


def _assert_warm_reuse(result: dict) -> None:
    """Loud-fail the warm-reuse gate unless reuse was observed (near-zero warm connect) and reconnect works."""
    warm_ms = result.get("warm_connect_ms")
    if not result.get("warm_reuse_observed") or warm_ms is None or warm_ms >= 5:
        raise core.SmokeTestFailure(
            f"WARM_REUSE FAIL ({result['role']}): warm reuse not observed / connect not near-zero: {result}"
        )
    if not result.get("reconnect_ok"):
        raise core.SmokeTestFailure(f"WARM_REUSE FAIL ({result['role']}): forced cold variant did not reconnect: {result}")


def lambda_warm_reuse(*, profile: str | None = None, region: str = "eu-west-2", json_output: bool = False) -> None:
    """D2 VP8: reader warm-connection reuse (2nd connect reused, near-zero) + forced cold reconnect."""
    result = _warm_reuse_probe("reader", profile=profile, region=region)
    _assert_warm_reuse(result)
    if json_output:
        print(json.dumps(result))
    else:
        print(
            f"LAMBDA_WARM_REUSE OK reader cold_ms={result['cold_connect_ms']} "
            f"warm_ms={result['warm_connect_ms']} reconnect_ok={result['reconnect_ok']}"
        )


def lambda_warm_reuse_writer(*, profile: str | None = None, region: str = "eu-west-2", json_output: bool = False) -> None:
    """D2 VP9: writer warm reuse + a write still commits under reuse + cold/warm latency (rec-2096)."""
    result = _warm_reuse_probe("writer", profile=profile, region=region)
    _assert_warm_reuse(result)

    # A single-statement write must still commit on the (warm) single-statement path with OCC intact.
    writer_url = core._function_url("writer")
    write_body = core._ok_json(
        core._sigv4_invoke(
            writer_url,
            {"action": "write", "record": {"rec_id": "rec-warm-reuse-probe", "payload": "w"}},
            profile=profile,
            region=region,
        )
    )
    if not write_body.get("ok"):
        raise core.SmokeTestFailure(f"WARM_REUSE_WRITER FAIL: write under reuse did not commit: {write_body}")
    result["write_ok"] = True
    result["write_occ_retries"] = write_body.get("occ_retries")

    if json_output:
        print(json.dumps(result))
    else:
        print(
            f"LAMBDA_WARM_REUSE_WRITER OK writer cold_ms={result['cold_connect_ms']} "
            f"warm_ms={result['warm_connect_ms']} write_ok=true occ_retries={result.get('write_occ_retries')}"
        )
