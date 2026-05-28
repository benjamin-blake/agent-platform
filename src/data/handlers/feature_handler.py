"""Lambda handler: Compute features from raw OHLCV data.

Step Functions state: ComputeFeatures
Input:  { "date": "2026-03-21", "raw_s3_key": "staging/raw/2026-03-21/ohlcv.parquet", ... }
Output: { "date": "2026-03-21", "enriched_s3_key": "staging/enriched/2026-03-21/market_data.parquet", "features_computed": 18 }
"""

import logging
import os
from datetime import date, timedelta
from io import BytesIO

import boto3
import pandas as pd

from src.common.config import config
from src.data.feature_engine import FeatureEngine

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_DATA_LAKE_BUCKET = os.environ.get(
    "S3_DATA_LAKE_BUCKET",
    config.get("aws.s3_data_lake_bucket", ""),
)


def handler(event, context):
    """Lambda entry point for ComputeFeatures step.

    Args:
        event: Output from FetchMarketData step.
        context: Lambda context.

    Returns:
        Dict passed to the next state in the state machine.
    """
    target_date_str = event["date"]
    raw_s3_key = event.get("raw_s3_key", "")

    if event.get("is_empty", False) or not raw_s3_key:
        logger.info("No raw data to process — skipping feature computation")
        return {
            "date": target_date_str,
            "enriched_s3_key": "",
            "features_computed": 0,
            "is_empty": True,
        }

    logger.info("ComputeFeatures: date=%s, raw=%s", target_date_str, raw_s3_key)

    # Read raw Parquet from S3
    raw_df = _read_parquet_from_s3(S3_DATA_LAKE_BUCKET, raw_s3_key)

    # Fetch historical rows from Iceberg for delta / z-score lookback.
    # Returns an empty DataFrame if insufficient history exists (first run)
    # — delta columns will be NaN in that case, which is acceptable.
    historical_df = _fetch_historical(target_date_str)

    # Compute features
    engine = FeatureEngine(
        technicals=config.get("data.features.technicals", True),
        sentiment=config.get("data.features.sentiment", True),
        fundamentals=config.get("data.features.fundamentals", True),
    )
    enriched_df = engine.compute(raw_df, historical_df=historical_df)

    # Count native feature columns added (exclude OHLCV + metadata columns).
    ohlcv_cols = {"timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume", "features"}
    feature_cols = [c for c in enriched_df.columns if c not in ohlcv_cols]
    features_computed = len(feature_cols)

    # Write enriched data to staging
    enriched_key = f"staging/enriched/{target_date_str}/market_data.parquet"
    _write_parquet_to_s3(enriched_df, S3_DATA_LAKE_BUCKET, enriched_key)

    logger.info(
        "Computed %d feature columns; wrote %d rows to s3://%s/%s",
        features_computed,
        len(enriched_df),
        S3_DATA_LAKE_BUCKET,
        enriched_key,
    )

    return {
        "date": target_date_str,
        "enriched_s3_key": enriched_key,
        "features_computed": features_computed,
        "is_empty": False,
    }


def _fetch_historical(target_date_str: str) -> pd.DataFrame:
    """Fetch recent rows from the Iceberg market_data table for delta lookback.

    Queries the last DELTA_LOOKBACK_DAYS of data prior to `target_date_str`.
    Returns an empty DataFrame if the table has no prior data or the query fails.

    Args:
        target_date_str: ISO date string of the current pipeline run (inclusive
                         end is excluded — we only want rows strictly before today).

    Returns:
        DataFrame with columns: symbol, timestamp, close, volume, features
        (and native feature columns if schema evolution has already run).
    """
    import awswrangler as wr

    database = os.environ.get("GLUE_DATABASE", config.get("aws.glue_database", "trading_formulas_db"))
    workgroup = os.environ.get("ATHENA_WORKGROUP", "primary")
    s3_output = f"s3://{S3_DATA_LAKE_BUCKET}/athena/query-results/"

    lookback_date = (date.fromisoformat(target_date_str) - timedelta(days=FeatureEngine.DELTA_LOOKBACK_DAYS)).isoformat()

    sql = f"""
        SELECT symbol, timestamp, trade_date, close, volume, features
        FROM {database}.market_data
        WHERE trade_date >= DATE '{lookback_date}'
          AND trade_date < DATE '{target_date_str}'
          AND (interval = '1d' OR interval IS NULL)
        ORDER BY symbol, timestamp
    """

    try:
        df = wr.athena.read_sql_query(
            sql=sql,
            database=database,
            workgroup=workgroup,
            s3_output=s3_output,
        )
        logger.info(
            "Fetched %d historical rows (lookback from %s to %s)",
            len(df),
            lookback_date,
            target_date_str,
        )
        return df
    except Exception as exc:
        logger.warning("Could not fetch historical data — delta columns will be NaN: %s", exc)
        return pd.DataFrame()


def _read_parquet_from_s3(bucket: str, key: str) -> pd.DataFrame:
    """Read a Parquet file from S3 into a DataFrame."""
    s3 = boto3.client("s3", region_name=config.aws_region)
    response = s3.get_object(Bucket=bucket, Key=key)
    buffer = BytesIO(response["Body"].read())
    return pd.read_parquet(buffer, engine="pyarrow")


def _write_parquet_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    """Write a DataFrame as Parquet to S3."""
    buffer = BytesIO()
    df.to_parquet(buffer, engine="pyarrow", compression="gzip", index=False)
    buffer.seek(0)

    s3 = boto3.client("s3", region_name=config.aws_region)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
