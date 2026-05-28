"""Unified S3 log read/write module with local fallback.

When S3_LOG_BUCKET is set, reads and writes go to S3.
When unset (local development), falls back to logs/{key} relative to repo root.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

try:
    import boto3

    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False

logger = logging.getLogger(__name__)

# Repo root: two levels up from this file (scripts/ -> repo root)
_REPO_ROOT = Path(__file__).parent.parent
_LOGS_DIR = _REPO_ROOT / "logs"

# ---------------------------------------------------------------------------
# OpsWriter write-through routing (Decision 50)
# Best-effort: failures are logged and never propagate to callers.
# ops_decisions has no automated write-through -- deferred to Phase 2.
# ---------------------------------------------------------------------------

_OPS_TABLE_ROUTING: dict[str, str] = {
    ".execution-plans.jsonl": "ops_execution_plans",
    ".session-telemetry.jsonl": "ops_session_log",
}
_OPS_PRIORITY_QUEUE_KEY = "priority-queue/.priority-queue.jsonl"

_ops_writer_instance = None


def _get_ops_writer():
    """Return (or lazily construct) the singleton OpsWriter, or None if unavailable."""
    global _ops_writer_instance  # noqa: PLW0603
    if _ops_writer_instance is None:
        try:
            from scripts.ops_writer import OpsWriter  # noqa: PLC0415

            _ops_writer_instance = OpsWriter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3_log_store: OpsWriter unavailable -- write-through disabled: %s", exc)
            return None
    return _ops_writer_instance


def get_backend() -> Literal["s3", "local"]:
    """Return 's3' if S3_LOG_BUCKET is set and boto3 is available, else 'local'."""
    bucket = os.environ.get("S3_LOG_BUCKET", "").strip()
    if bucket and _BOTO3_AVAILABLE:
        return "s3"
    return "local"


def _get_bucket() -> str:
    """Return the S3 bucket name from environment."""
    return os.environ.get("S3_LOG_BUCKET", "").strip()


def _get_s3_client():  # type: ignore[return]
    """Return a boto3 S3 client using AWS_PROFILE if set."""
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 is not available; cannot use S3 backend")
    profile = os.environ.get("AWS_PROFILE")
    if profile:
        session = boto3.Session(profile_name=profile)
        return session.client("s3", region_name="eu-west-2")
    return boto3.client("s3", region_name="eu-west-2")


def _local_path(key: str) -> Path:
    """Map a log key to a local file path under logs/."""
    return _LOGS_DIR / key


def read_jsonl(key: str) -> list[dict]:
    """Read all lines from S3 or local file.

    Args:
        key: Log key, e.g. '.recommendations-log.jsonl' or 'recommendations/recs.jsonl'

    Returns:
        List of parsed JSON objects. Empty list if file does not exist or is empty.
    """
    if get_backend() == "s3":
        return _read_jsonl_s3(key)
    return _read_jsonl_local(key)


def _read_jsonl_local(key: str) -> list[dict]:
    path = _local_path(key)
    if not path.exists():
        return []
    results: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                results.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON on line %d of %s: %s", lineno, path, exc)
    return results


def _read_jsonl_s3(key: str) -> list[dict]:
    bucket = _get_bucket()
    try:
        client = _get_s3_client()
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response") and exc.response.get("Error", {}).get("Code") == "NoSuchKey":  # type: ignore[union-attr]
            return []
        logger.warning("S3 read failed for %s/%s, falling back to local: %s", bucket, key, exc)
        return _read_jsonl_local(key)

    results: list[dict] = []
    for lineno, line in enumerate(body.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            results.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed JSON on line %d of s3://%s/%s: %s", lineno, bucket, key, exc)
    return results


def append_jsonl(key: str, entry: dict) -> bool:
    """Append a single JSON line to S3 or local file.

    Args:
        key: Log key, e.g. '.retro-lite-log.jsonl'
        entry: Dictionary to serialise as a single JSON line.

    Returns:
        True on success, False on failure.
    """
    backend = get_backend()
    if backend == "local" and os.environ.get("PYTEST_CURRENT_TEST"):
        logger.warning(
            "Skipping local append for %s (PYTEST_CURRENT_TEST set)",
            key,
        )
        return True
    if backend == "s3":
        result = _append_jsonl_s3(key, entry)
    else:
        result = _append_jsonl_local(key, entry)

    # OpsWriter write-through (best-effort, never propagates failure)
    if result:
        table = _OPS_TABLE_ROUTING.get(key)
        if table:
            try:
                ops = _get_ops_writer()
                if ops is not None:
                    ops.write(table, entry)
            except Exception as exc:  # noqa: BLE001
                logger.warning("s3_log_store: ops write-through failed for %s->%s: %s", key, table, exc)

    return result


def _append_jsonl_local(key: str, entry: dict) -> bool:
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        logger.error("Failed to append to %s: %s", path, exc)
        return False


def _append_jsonl_s3(key: str, entry: dict) -> bool:
    bucket = _get_bucket()
    new_line = json.dumps(entry, ensure_ascii=False) + "\n"
    try:
        client = _get_s3_client()
        # Read existing content
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            existing = response["Body"].read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response") and exc.response.get("Error", {}).get("Code") == "NoSuchKey":  # type: ignore[union-attr]
                existing = ""
            else:
                logger.warning("S3 read failed for append %s/%s, falling back to local: %s", bucket, key, exc)
                return _append_jsonl_local(key, entry)
        # Write updated content
        updated = existing + new_line
        client.put_object(Bucket=bucket, Key=key, Body=updated.encode("utf-8"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 append failed for %s/%s, falling back to local: %s", bucket, key, exc)
        return _append_jsonl_local(key, entry)


def overwrite_jsonl(key: str, entries: list[dict]) -> bool:
    """Write *entries* as a newline-delimited JSON file, replacing any existing content.

    Unlike ``append_jsonl`` (which appends a single entry), this function
    replaces the entire file so downstream consumers always see a fresh snapshot.

    Args:
        key: Log key, e.g. ``'priority-queue/.priority-queue.jsonl'``
        entries: List of dicts to serialise.  An empty list writes an empty file.

    Returns:
        True on success, False on failure.
    """
    backend = get_backend()
    if backend == "local" and os.environ.get("PYTEST_CURRENT_TEST"):
        logger.warning(
            "Skipping local overwrite for %s (PYTEST_CURRENT_TEST set)",
            key,
        )
        return True
    if backend == "s3":
        result = _overwrite_jsonl_s3(key, entries)
    else:
        result = _overwrite_jsonl_local(key, entries)

    # OpsWriter write-through for priority queue (best-effort, never propagates failure)
    if result and key == _OPS_PRIORITY_QUEUE_KEY and entries:
        import uuid as _uuid  # noqa: PLC0415

        queue_run_id = str(_uuid.uuid4())
        try:
            ops = _get_ops_writer()
            if ops is not None:
                for entry in entries:
                    enriched = dict(entry)
                    enriched.setdefault("queue_run_id", queue_run_id)
                    ops.write("ops_priority_queue", enriched)
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3_log_store: ops write-through failed for priority_queue: %s", exc)

    return result


def _overwrite_jsonl_local(key: str, entries: list[dict]) -> bool:
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        logger.error("Failed to overwrite %s: %s", path, exc)
        return False


def _overwrite_jsonl_s3(key: str, entries: list[dict]) -> bool:
    bucket = _get_bucket()
    body = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    if entries:
        body += "\n"
    try:
        client = _get_s3_client()
        client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to overwrite S3 %s/%s: %s", bucket, key, exc)
        return False


def list_keys(prefix: str) -> list[str]:
    """List keys under prefix (S3) or matching glob pattern (local).

    Args:
        prefix: Key prefix for S3, or glob pattern suffix for local (relative to logs/).

    Returns:
        List of key strings.
    """
    if get_backend() == "s3":
        return _list_keys_s3(prefix)
    return _list_keys_local(prefix)


def _list_keys_local(prefix: str) -> list[str]:
    base = _LOGS_DIR
    # Interpret prefix as a glob pattern relative to logs/
    return [str(p.relative_to(_LOGS_DIR)).replace("\\", "/") for p in base.glob(prefix)]


def _list_keys_s3(prefix: str) -> list[str]:
    bucket = _get_bucket()
    try:
        client = _get_s3_client()
        paginator = client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 list failed for %s/%s, returning empty: %s", bucket, prefix, exc)
        return []


# ---------------------------------------------------------------------------
# Agent findings helpers
# ---------------------------------------------------------------------------


def write_timestamped_findings(agent_name: str, findings: list[dict]) -> str:
    """Write a list of findings to a timestamped JSONL file for the given agent.

    The key follows the convention ``agents/{agent_name}/{ISO-timestamp}.jsonl``.
    Each dict in *findings* is serialised as a separate JSON line.

    Args:
        agent_name: Name of the agent (e.g. ``"doc-freshness"``).
        findings: List of finding dicts to write.

    Returns:
        The S3 key (or local relative path) written. Empty string on failure.
    """
    from datetime import datetime, timezone

    # Use hyphens instead of colons in the time component for Windows
    # filesystem compatibility (colons are invalid in Windows paths).
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    key = f"agents/{agent_name}/{timestamp}.jsonl"

    if get_backend() == "s3":
        bucket = _get_bucket()
        body = "\n".join(json.dumps(f, ensure_ascii=False) for f in findings)
        if findings:
            body += "\n"
        try:
            client = _get_s3_client()
            client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
            logger.info("Wrote %d findings to s3://%s/%s", len(findings), bucket, key)
            return key
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write findings to S3 %s/%s: %s", bucket, key, exc)
            return ""
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for finding in findings:
                    fh.write(json.dumps(finding, ensure_ascii=False) + "\n")
            logger.info("Wrote %d findings to %s", len(findings), path)
            return key
        except OSError as exc:
            logger.error("Failed to write findings to %s: %s", path, exc)
            return ""


def list_agent_findings(agent_name: str | None = None) -> list[str]:
    """List finding keys under ``agents/`` (or ``agents/{agent_name}/``).

    Args:
        agent_name: If provided, scope the listing to this agent's prefix.

    Returns:
        Sorted list of key strings (JSONL files only).
    """
    if get_backend() == "s3":
        prefix = f"agents/{agent_name}/" if agent_name else "agents/"
        return sorted(list_keys(prefix))
    # Local: use glob to find only .jsonl files (colons are safe in glob patterns)
    glob_pattern = f"agents/{agent_name}/*.jsonl" if agent_name else "agents/**/*.jsonl"
    base = _LOGS_DIR
    keys = [str(p.relative_to(base)).replace("\\", "/") for p in base.glob(glob_pattern) if p.is_file()]
    return sorted(keys)


def read_all_agent_findings() -> list[dict]:
    """Read every JSONL file under ``agents/*/`` and return all entries.

    Each entry has a ``"source"`` field added containing the agent name and
    timestamp extracted from the key path (``agents/{name}/{timestamp}.jsonl``).

    Returns:
        List of finding dicts, in key order.
    """
    keys = list_agent_findings()
    results: list[dict] = []
    for key in keys:
        # Extract source metadata from key: agents/{agent_name}/{timestamp}.jsonl
        parts = key.split("/")
        agent_source = parts[1] if len(parts) >= 3 else "unknown"
        timestamp_source = parts[2].replace(".jsonl", "") if len(parts) >= 3 else ""
        source = f"{agent_source}/{timestamp_source}" if timestamp_source else agent_source

        entries = read_jsonl(key)
        for entry in entries:
            enriched = dict(entry)
            enriched.setdefault("source", source)
            results.append(enriched)
    return results
