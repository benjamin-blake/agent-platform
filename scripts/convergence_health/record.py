"""Convergence-record read + time/backlog helpers (CD.35 Wave 6 / T2.35).

Reads convergence/personal/sandbox.json from S3 and derives red_since /
red_age_hours / record_age_hours, plus counts merged terraform/personal/
commits since the record's commit_sha. All external dependencies (S3
client, git runner) are injected so unit tests can mock them without live
AWS. Part of the scripts.convergence_health package -- see
scripts/convergence_health/__init__.py for the full public surface.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Optional

CONVERGENCE_BUCKET = "agent-platform-data-lake"
CONVERGENCE_KEY = "convergence/personal/sandbox.json"


def read_convergence_record(
    s3_client: Any,
    bucket: str = CONVERGENCE_BUCKET,
    key: str = CONVERGENCE_KEY,
) -> Optional[dict[str, Any]]:
    """Read the convergence record from S3; return None on NoSuchKey or missing object."""
    import json  # noqa: PLC0415

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc) + type(exc).__name__
        if any(marker in exc_str for marker in ("NoSuchKey", "404", "NoSuchBucket")):
            return None
        raise


def derive_red_since(record: dict[str, Any]) -> datetime:
    """Return the datetime when the record entered the current red episode.

    Uses drift_detected_at when present -- a drift-flip preserves the prior
    green timestamp in the bare 'timestamp' field, so timestamp understates
    red-age on a drift-flip. Falls back to 'timestamp'.
    """
    raw = record.get("drift_detected_at") or record.get("timestamp") or ""
    return _parse_utc(raw)


def red_age_hours(record: dict[str, Any], now: Optional[datetime] = None) -> float:
    """Return how many hours the record has been red (0.0 if green or unknown)."""
    if record.get("status") != "red":
        return 0.0
    if now is None:
        now = datetime.now(timezone.utc)
    since = derive_red_since(record)
    delta = now - since
    return max(0.0, delta.total_seconds() / 3600.0)


def record_age_hours(record: dict[str, Any], now: Optional[datetime] = None) -> float:
    """Return hours since the record's 'timestamp' field, regardless of status.

    Unlike red_age_hours (red-episode-only, prefers drift_detected_at), this measures plain
    record staleness -- how long since the record was last written. Used by the stale-green-
    backlog trigger to distinguish a healthy in-flight merge (record just written, backlog
    clears within minutes) from a persistently stale green record.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    since = _parse_utc(record.get("timestamp") or "")
    delta = now - since
    return max(0.0, delta.total_seconds() / 3600.0)


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp to a timezone-aware datetime."""
    ts = ts.rstrip("Z")
    if not ts:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def count_unapplied_tf_commits(
    commit_sha: str,
    git_runner: Optional[Callable[[list[str]], str]] = None,
) -> int:
    """Count merged terraform/personal/** commits since commit_sha via git log.

    Returns 0 on any error (record SHA may predate the current clone depth).
    """
    if not commit_sha:
        return 0

    def _default_runner(cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()

    runner = git_runner or _default_runner
    try:
        output = runner(
            [
                "git",
                "log",
                f"{commit_sha}..HEAD",
                "--oneline",
                "--",
                "terraform/personal/",
            ]
        )
        if not output:
            return 0
        return len([line for line in output.splitlines() if line.strip()])
    except Exception:  # noqa: BLE001
        return 0
