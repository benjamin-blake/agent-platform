"""Ops Compaction Lambda handler.

Triggered by S3 ObjectCreated events on the staging/ prefix of the
agent-logs bucket.  Parses the S3 key to extract the ops table name and
trade_date partition, then calls OpsWriter.compact() to write the staged
rows into the Iceberg table.

Also accepts {"force_table": "...", "force_date": "..."} event fields for
manual invocation (smoke testing, backfill).

Key format: staging/{table_name}/trade_date={YYYY-MM-DD}/batch-{uuid}.jsonl
"""

from __future__ import annotations

import logging
from typing import Any

# TABLE_NAMES is a plain list constant -- safe to import at module level.
# OpsWriter is imported lazily inside the handler to avoid awswrangler ImportError.
try:
    from scripts.ops_writer import TABLE_NAMES
except ImportError:  # pragma: no cover
    TABLE_NAMES = []  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ANN401
    """Lambda entry point for ops staging compaction.

    Args:
        event: S3 ObjectCreated event or manual invocation with force_table/force_date.
        context: Lambda context object (unused).

    Returns:
        Dict with statusCode, rows_compacted, table, and trade_date.
    """
    # OpsWriter imported lazily -- awswrangler is only available on Lambda.
    from scripts.ops_writer import OpsWriter  # noqa: PLC0415

    # Manual invocation path (smoke testing / backfill)
    if "force_table" in event and "force_date" in event:
        table_name: str = event["force_table"]
        trade_date: str = event["force_date"]
    else:
        # S3 event path
        try:
            key: str = event["Records"][0]["s3"]["object"]["key"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("ops_compaction_handler: malformed S3 event -- missing Records/key: %s", exc)
            return {"statusCode": 400, "error": "malformed S3 event", "rows_compacted": 0}

        # key format: staging/{table_name}/trade_date={YYYY-MM-DD}/batch-{uuid}.jsonl
        parts = key.split("/")
        if len(parts) < 3:
            logger.warning("ops_compaction_handler: unexpected key format %r -- skipping", key)
            return {"statusCode": 200, "rows_compacted": 0}

        table_name = parts[1]
        # parts[2] format: dt=2026-04-21 (ops tables) or trade_date=2026-04-21 (telemetry tables)
        date_segment = parts[2]
        if "=" in date_segment:
            trade_date = date_segment.split("=", 1)[1]
        else:
            logger.warning("ops_compaction_handler: could not parse date from %r", date_segment)
            return {"statusCode": 200, "rows_compacted": 0}

    if table_name not in TABLE_NAMES:
        logger.warning(
            "ops_compaction_handler: unknown table %r -- skipping (valid: %s)",
            table_name,
            TABLE_NAMES,
        )
        return {"statusCode": 200, "rows_compacted": 0}

    logger.info("ops_compaction_handler: compacting %s for trade_date=%s", table_name, trade_date)
    writer = OpsWriter()
    row_count = writer.compact(table_name, trade_date)
    logger.info("ops_compaction_handler: compacted %d rows from %s", row_count, table_name)

    return {
        "statusCode": 200,
        "rows_compacted": row_count,
        "table": table_name,
        "trade_date": trade_date,
    }
