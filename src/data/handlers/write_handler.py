"""Lambda handler: Write enriched data to Iceberg market_data table.

Step Functions state: WriteToIceberg
Input:  { "date": "2026-03-21", "enriched_s3_key": "staging/enriched/2026-03-21/market_data.parquet", ... }
Output: { "date": "2026-03-21", "rows_written": 97, "source": "yfinance" }

Uses awswrangler.athena.to_iceberg() via the AWSSDKPandas managed layer.
No pyiceberg dependency required.
"""

import logging
import os
from io import BytesIO

import boto3
import pandas as pd

from src.common.config import config
from src.data.writer import IcebergWriter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_DATA_LAKE_BUCKET = os.environ.get(
    "S3_DATA_LAKE_BUCKET",
    config.get("aws.s3_data_lake_bucket", ""),
)


def handler(event, context):
    """Lambda entry point for WriteToIceberg step.

    Args:
        event: Output from ComputeFeatures step.
        context: Lambda context.

    Returns:
        Dict with write results.
    """
    target_date_str = event["date"]
    enriched_s3_key = event.get("enriched_s3_key", "")

    if event.get("is_empty", False) or not enriched_s3_key:
        logger.info("No enriched data to write — skipping Iceberg write")
        return {
            "date": target_date_str,
            "rows_written": 0,
            "source": "yfinance",
            "is_empty": True,
        }

    logger.info("WriteToIceberg: date=%s, enriched=%s", target_date_str, enriched_s3_key)

    # Read enriched Parquet from S3
    enriched_df = _read_parquet_from_s3(S3_DATA_LAKE_BUCKET, enriched_s3_key)

    # Write to Iceberg via MERGE upsert
    source = config.get("data.provider", "yfinance")
    writer = IcebergWriter()
    rows_written = writer.write(enriched_df, source=source, trade_date=target_date_str, interval="1d")

    logger.info("Wrote %d rows to Iceberg (trade_date=%s)", rows_written, target_date_str)

    return {
        "date": target_date_str,
        "rows_written": rows_written,
        "source": source,
        "is_empty": False,
    }


def _read_parquet_from_s3(bucket: str, key: str) -> pd.DataFrame:
    """Read a Parquet file from S3 into a DataFrame."""
    s3 = boto3.client("s3", region_name=config.aws_region)
    response = s3.get_object(Bucket=bucket, Key=key)
    buffer = BytesIO(response["Body"].read())
    return pd.read_parquet(buffer, engine="pyarrow")
