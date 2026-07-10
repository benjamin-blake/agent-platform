"""DuckLake CloudWatch metric emission (EC9; split from ducklake_runtime).

Owner concern: best-effort CloudWatch metric emission for the write path. No dependency on
ducklake_scd2_schema or any other DuckLake module -- this is a pure AWS-emission leaf.
"""

from __future__ import annotations

from typing import Any, Callable

# CloudWatch metric namespace for OCC-retry + commit-latency emission (EC9).
CLOUDWATCH_NAMESPACE = "DuckLakeWriter"


def emit_metric(
    name: str,
    value: float,
    *,
    namespace: str = CLOUDWATCH_NAMESPACE,
    unit: str = "None",
    profile: str | None = None,
    client: Any = None,
) -> None:
    """Emit a single CloudWatch metric datum. Best-effort: a metrics failure must not fail a write.

    Pass `client` to inject a CloudWatch client (tests / a shared client). In the Lambda the ambient
    execution-role credentials are used (no profile).
    """
    try:
        if client is None:
            import boto3  # noqa: PLC0415

            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            session = boto3.Session(profile_name=resolve_aws_profile(profile))
            client = session.client("cloudwatch")
        client.put_metric_data(
            Namespace=namespace,
            MetricData=[{"MetricName": name, "Value": float(value), "Unit": unit}],
        )
    except Exception:  # noqa: BLE001 -- metrics are observability, never a write-blocking failure
        pass


def make_metric_sink(
    *, namespace: str = CLOUDWATCH_NAMESPACE, client: Any = None, profile: str | None = None
) -> Callable[[str, float], None]:
    """Build a metric_sink(name, value) closure for write_scd2 that emits to CloudWatch."""

    def _sink(name: str, value: float) -> None:
        unit = "Milliseconds" if name.endswith("Ms") else "Count"
        emit_metric(name, value, namespace=namespace, unit=unit, client=client, profile=profile)

    return _sink
