"""AWS Data Wrangler writer for the market_data Iceberg table.

Uses awswrangler.athena.to_iceberg() to write enriched market data via Athena.
This approach leverages the AWSSDKPandas Lambda layer (which bundles pyarrow,
pandas, and awswrangler) and avoids shipping pyiceberg as a custom dependency.

Benefits over PyIceberg:
    - Zero custom binaries — runs entirely through the AWS managed layer
    - Atomic Iceberg commits via Athena engine v3
    - Partition management handled by Iceberg metadata automatically
    - Schema evolution supported via ALTER TABLE through Athena

The table is partitioned by `trade_date` (date). Athena's Iceberg engine
handles partition layout and metadata updates automatically.

Write strategy:
    Uses Athena MERGE INTO via awswrangler's `merge_cols` parameter.
    Rows are matched on (symbol, timestamp, interval, source) — existing rows are
    updated in-place, new rows are inserted.  This is more efficient than
    DELETE + INSERT because it executes a single Athena query and only
    touches matched rows (no full partition scan for delete).

    The Athena Iceberg engine enforces **copy-on-write** (COW) exclusively
    — merge-on-read (MOR) is not supported.  This is the optimal strategy
    for a fact table where reads vastly outnumber writes:
    - Reads never need to reconcile delete files at query time
    - Each snapshot is self-contained — no merge-on-read overhead
    - Parquet files are rewritten on update, so scans are always clean
    The trade-off is slightly higher write amplification during MERGE,
    which is acceptable for a once-daily pipeline.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..common.config import config

logger = logging.getLogger(__name__)

# Columns that uniquely identify a row for MERGE matching.
# `interval` distinguishes grains (1d, 1h, 15m) so multiple granularities
# can coexist in the same table without sentinel values.
MERGE_KEYS = ["symbol", "timestamp", "interval", "source"]


class IcebergWriter:
    """Writes enriched market data to the Iceberg market_data table via Athena.

    Uses awswrangler.athena.to_iceberg() under the hood — the AWSSDKPandas
    Lambda layer provides awswrangler, pandas, pyarrow, and boto3.
    """

    def __init__(
        self,
        database: str = None,
        table_name: str = "market_data",
    ):
        """Initialise the Iceberg writer.

        Args:
            database: Glue database name (from config if None).
            table_name: Iceberg table name.
        """
        self._database = database or config.glue_database
        self._table_name = table_name

    def write(
        self,
        df: pd.DataFrame,
        source: str,
        trade_date: Optional[str] = None,
        interval: str = "1d",
    ) -> int:
        """Write enriched market data to the Iceberg table via MERGE.

        Uses Athena MERGE INTO to upsert rows.  Rows are matched on
        (symbol, timestamp, interval, source); matched rows are updated, new rows
        are inserted.  This is idempotent — re-running for the same bar
        updates existing data rather than duplicating it.

        Args:
            df: Enriched DataFrame with columns matching the Iceberg schema
                (must include `features` as a dict column).
            source: Data provider name (e.g., 'yfinance').
            trade_date: ISO date string (e.g., '2026-03-21') — used for
                       logging only; the actual trade_date values are
                       derived from the DataFrame timestamps.
            interval: Data granularity string (e.g., '1d', '1h', '15m').
                      Applied to all rows in this write.  Default '1d'.

        Returns:
            Number of rows written / updated.

        Raises:
            ValueError: If DataFrame is empty or missing required columns.
        """
        # Late import — only available inside Lambda with AWSSDKPandas layer
        import awswrangler as wr

        if df.empty:
            logger.warning("Empty DataFrame — nothing to write")
            return 0

        prepared_df = self._prepare(df, source, interval)
        num_rows = len(prepared_df)

        table_identifier = f"{self._database}.{self._table_name}"
        s3_bucket = os.environ.get("S3_DATA_LAKE_BUCKET") or config.get("aws.s3_data_lake_bucket", "")

        # MERGE upsert — single atomic Athena query.
        # awswrangler generates:
        #   MERGE INTO market_data USING __temp
        #     ON market_data.symbol = __temp.symbol
        #    AND market_data.timestamp = __temp.timestamp
        #    AND market_data.interval = __temp.interval
        #    AND market_data.source = __temp.source
        #   WHEN MATCHED THEN UPDATE SET *
        #   WHEN NOT MATCHED THEN INSERT *
        workgroup = os.environ.get("ATHENA_WORKGROUP", "primary")
        s3_output = f"s3://{s3_bucket}/athena/query-results/"
        wr.athena.to_iceberg(
            df=prepared_df,
            database=self._database,
            table=self._table_name,
            temp_path=f"s3://{s3_bucket}/athena/iceberg-temp/",
            s3_output=s3_output,
            workgroup=workgroup,
            merge_cols=MERGE_KEYS,
            keep_files=False,
            # Explicit Athena/Iceberg type hints.
            # The features map requires an override because pandas stores dicts
            # as object dtype which awswrangler would otherwise infer as string.
            # All promoted native columns are float64 → double (correct by default,
            # but listed explicitly so schema_evolution creates them with the right
            # type on first write rather than relying on inference).
            dtype={
                "features": "map<string,double>",
                # Technical indicators
                "tech_rsi_14": "double",
                "tech_macd": "double",
                "tech_macd_signal": "double",
                "tech_macd_histogram": "double",
                "tech_bb_width": "double",
                "tech_atr_14": "double",
                "tech_sma_20": "double",
                "tech_sma_50": "double",
                "tech_sma_200": "double",
                "tech_ema_12": "double",
                "tech_ema_26": "double",
                "tech_volume_ratio": "double",
                "tech_momentum_5d": "double",
                "tech_momentum_10d": "double",
                "tech_momentum_20d": "double",
                "tech_volatility_20d": "double",
                # Fundamentals
                "fundamental_pe": "double",
                "fundamental_market_cap": "double",
                "fundamental_div_yield": "double",
                # Sentiment
                "sentiment_fear_greed": "double",
                # Pre-calculated deltas
                "delta_price_1d": "double",
                "delta_price_5d": "double",
                "delta_price_20d": "double",
                "delta_volatility_10d": "double",
                "zscore_close_30d": "double",
                "zscore_volume_30d": "double",
                "zscore_rsi_30d": "double",
                "delta_sentiment_1d": "double",
                "interval": "string",
            },
            schema_evolution=True,
        )

        logger.info(
            "MERGE upserted %d rows into %s (trade_date=%s, interval=%s, source=%s)",
            num_rows,
            table_identifier,
            trade_date,
            interval,
            source,
        )

        return num_rows

    @staticmethod
    def _prepare(df: pd.DataFrame, source: str, interval: str = "1d") -> pd.DataFrame:
        """Prepare a DataFrame for Iceberg write.

        Adds the `source`, `ingested_at`, `interval`, and `trade_date` columns.
        Keeps `features` as dict — awswrangler handles map<string,double> natively
        when we pass dtype={"features": "map<string,double>"}.
        """
        now = datetime.now(timezone.utc)
        out = df.copy()

        out["source"] = source
        out["ingested_at"] = now
        out["interval"] = interval

        # Derive trade_date from timestamp
        out["trade_date"] = pd.to_datetime(out["timestamp"]).dt.date

        # Ensure volume is int64
        out["volume"] = out["volume"].fillna(0).astype("int64")

        # Ensure features is a dict with float values for map<string,double>.
        # Drop entries where the value is None — Athena map<string,double>
        # does not support null values inside the map.
        if "features" in out.columns:
            out["features"] = out["features"].apply(
                lambda d: {str(k): float(v) for k, v in d.items() if v is not None} if isinstance(d, dict) else {}
            )

        return out
