"""Shared primitives for the scripts/preflight package.

SOLE source of shared constants, path primitives, and reader/timestamp helpers used by every
session_preflight domain module. No dependency on scripts.session_preflight (no import cycle).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.aws_profile import resolve_aws_profile  # noqa: F401
from scripts.s3_log_store import get_backend, read_jsonl  # noqa: F401
from src.common.iceberg_reader import make_reader as _make_reader  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent.parent
TERRAFORM_DIR = ROOT / "terraform"
SESSION_LOG_FILE = ROOT / "docs" / "SESSION_LOG.md"
RECOMMENDATIONS_FILE = ROOT / "logs" / ".recommendations-log.jsonl"
ROADMAP_FILE = ROOT / "docs" / "ROADMAP-PRODUCT.md"
ROADMAP_PLATFORM_PATH = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
ROADMAP_PRODUCT_PATH = ROOT / "docs" / "ROADMAP-PRODUCT.yaml"
DECISIONS_FILE = ROOT / "docs" / "DECISIONS.md"
STRATEGIC_REVIEW_LOOKBACK_DAYS = 30
PRIORITY_QUEUE_FILE = ROOT / "logs" / "priority-queue" / ".priority-queue.jsonl"
_NON_AUTOMATABLE_SOFTCAP = 250


# Sentinel default distinguishing "no cache rows supplied -> use the reader (back-compat / tests)"
# from "cache rows supplied but None -> reader pull failed -> degrade" (a real None is meaningful).
_READER_SENTINEL: object = object()


def _row_ts(row: dict, field: str = "created_timestamp") -> datetime | None:
    """Parse a row timestamp field (ISO string or datetime) into a UTC-aware datetime, or None."""
    val = row.get(field)
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if hasattr(val, "isoformat"):  # date / other temporal
        try:
            return datetime.fromisoformat(val.isoformat()).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    return _parse_ts_utc(str(val))


def _parse_ts_utc(ts: str) -> datetime | None:
    """Parse an ISO-like timestamp string into a UTC-aware datetime, or None on failure."""
    ts = ts.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None
