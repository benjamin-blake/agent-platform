"""Lambda handler: Fetch raw OHLCV data from yfinance.

Step Functions state: FetchMarketData
Input:  { "date": "2026-03-21" }
Output: { "date": "2026-03-21", "raw_s3_key": "staging/raw/2026-03-21/ohlcv.parquet", "symbols_fetched": 97 }
"""

import logging
import os
from datetime import date
from io import BytesIO

import boto3
import pandas as pd

from src.common.config import config
from src.data.universe import SymbolUniverse
from src.data.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_DATA_LAKE_BUCKET = os.environ.get(
    "S3_DATA_LAKE_BUCKET",
    config.get("aws.s3_data_lake_bucket", ""),
)


def handler(event, context):
    """Lambda entry point for FetchMarketData step.

    Args:
        event: Step Functions input with 'date' key.
        context: Lambda context.

    Returns:
        Dict passed to the next state in the state machine.
    """
    date_input = event.get("date")
    target_date_str = date.today().isoformat() if not date_input or date_input == "auto" else date_input
    target_date = date.fromisoformat(target_date_str)

    logger.info("FetchMarketData: date=%s", target_date)

    # Resolve symbol universe
    universe_name = config.get("data.universe", "ftse_100")
    symbols = SymbolUniverse.get_universe(universe_name)

    # Fetch OHLCV
    provider = YFinanceProvider(
        retry_attempts=config.get("data.retry_attempts", 3),
        retry_delay_seconds=config.get("data.retry_delay_seconds", 60),
    )
    raw_df = provider.fetch_daily(symbols, target_date, target_date)

    if raw_df.empty:
        logger.warning("No data returned — possible holiday or weekend")
        return {
            "date": target_date_str,
            "raw_s3_key": "",
            "symbols_fetched": 0,
            "is_empty": True,
        }

    # Write raw data to staging area on S3 as Parquet
    s3_key = f"staging/raw/{target_date_str}/ohlcv.parquet"
    _write_parquet_to_s3(raw_df, S3_DATA_LAKE_BUCKET, s3_key)

    symbols_fetched = raw_df["symbol"].nunique()
    logger.info("Wrote %d rows (%d symbols) to s3://%s/%s", len(raw_df), symbols_fetched, S3_DATA_LAKE_BUCKET, s3_key)

    return {
        "date": target_date_str,
        "raw_s3_key": s3_key,
        "symbols_fetched": symbols_fetched,
        "is_empty": False,
    }


def _write_parquet_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    """Write a DataFrame as Parquet to S3."""
    buffer = BytesIO()
    df.to_parquet(buffer, engine="pyarrow", compression="gzip", index=False)
    buffer.seek(0)

    s3 = boto3.client("s3", region_name=config.aws_region)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
