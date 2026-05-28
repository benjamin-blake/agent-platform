"""Market data pipeline orchestrator.

Coordinates the full ingestion workflow:
    1. Fetch raw OHLCV from a MarketDataProvider
    2. Compute features via FeatureEngine
    3. Validate data quality
    4. Write to Iceberg via IcebergWriter

The pipeline is idempotent — re-running for the same date overwrites
existing data rather than duplicating it.

Can be invoked directly for local testing:
    python -m src.data.pipeline --dry-run --date 2026-03-20
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import pandas as pd

from ..common.config import config
from .feature_engine import FeatureEngine
from .provider_base import MarketDataProvider
from .universe import SymbolUniverse
from .writer import IcebergWriter
from .yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""

    trade_date: str
    source: str
    symbols_requested: int
    symbols_received: int
    rows_written: int
    features_computed: int
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.rows_written > 0 and len(self.errors) == 0


class MarketDataPipeline:
    """Orchestrates market data ingestion from fetch to Iceberg write.

    Designed to be called from:
        - Lambda handlers (Step Functions)
        - CLI for local testing
        - Direct Python invocation
    """

    def __init__(
        self,
        provider: MarketDataProvider = None,
        feature_engine: FeatureEngine = None,
        writer: IcebergWriter = None,
    ):
        """Initialise the pipeline with configurable components.

        Args:
            provider: Market data provider (default: YFinanceProvider).
            feature_engine: Feature computation engine (default: all features enabled).
            writer: Iceberg writer (default: overwrite mode).
        """
        self.provider = provider or YFinanceProvider(
            retry_attempts=config.get("data.retry_attempts", 3),
            retry_delay_seconds=config.get("data.retry_delay_seconds", 60),
        )
        self.feature_engine = feature_engine or FeatureEngine(
            technicals=config.get("data.features.technicals", True),
            sentiment=config.get("data.features.sentiment", True),
            fundamentals=config.get("data.features.fundamentals", True),
        )
        self.writer = writer or IcebergWriter(
            overwrite_existing=config.get("data.overwrite_existing", True),
        )

    def run(
        self,
        target_date: Optional[date] = None,
        symbols: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> PipelineResult:
        """Execute the full pipeline for a given date.

        Args:
            target_date: Date to ingest (default: today).
            symbols: Override symbol list (default: from config universe).
            dry_run: If True, fetch and compute but don't write to Iceberg.

        Returns:
            PipelineResult with execution details.
        """
        import time

        start_time = time.time()
        target_date = target_date or date.today()
        trade_date_str = target_date.isoformat()

        # Resolve symbols
        if symbols is None:
            universe_name = config.get("data.universe", "ftse_100")
            symbols = SymbolUniverse.get_universe(universe_name)

        result = PipelineResult(
            trade_date=trade_date_str,
            source=self.provider.source_name,
            symbols_requested=len(symbols),
            symbols_received=0,
            rows_written=0,
            features_computed=0,
        )

        logger.info(
            "Pipeline starting: date=%s, source=%s, symbols=%d",
            trade_date_str,
            self.provider.source_name,
            len(symbols),
        )

        # Step 1: Fetch raw OHLCV
        try:
            raw_df = self.provider.fetch_daily(symbols, target_date, target_date)
        except Exception as exc:
            error_msg = f"Fetch failed: {exc}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.duration_seconds = time.time() - start_time
            return result

        if raw_df.empty:
            logger.warning("No data returned — possible holiday or weekend")
            result.duration_seconds = time.time() - start_time
            return result

        result.symbols_received = raw_df["symbol"].nunique()
        logger.info("Fetched %d rows for %d symbols", len(raw_df), result.symbols_received)

        # Step 2: Compute features
        try:
            enriched_df = self.feature_engine.compute(raw_df)
            # Count average features per row
            if "features" in enriched_df.columns:
                avg_features = enriched_df["features"].apply(lambda d: len(d) if isinstance(d, dict) else 0).mean()
                result.features_computed = int(avg_features)
        except Exception as exc:
            error_msg = f"Feature computation failed: {exc}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.duration_seconds = time.time() - start_time
            return result

        logger.info(
            "Computed ~%d features per row for %d rows",
            result.features_computed,
            len(enriched_df),
        )

        # Step 3: Validate
        validation_errors = self._validate(enriched_df)
        if validation_errors:
            for err in validation_errors:
                logger.warning("Validation: %s", err)
                result.errors.append(err)

        # Step 4: Write to Iceberg (or dry-run)
        if dry_run:
            logger.info("DRY RUN — skipping Iceberg write")
            print("\n=== Dry Run Result ===")
            print(f"Date: {trade_date_str}")
            print(f"Source: {self.provider.source_name}")
            print(f"Rows: {len(enriched_df)}")
            print(f"Symbols: {result.symbols_received}")
            print(f"Features per row: ~{result.features_computed}")
            print("\nSample data (first 5 rows):")
            print(enriched_df.head().to_string())
            if "features" in enriched_df.columns:
                print("\nSample features (first row):")
                first_features = enriched_df.iloc[0]["features"]
                if isinstance(first_features, dict):
                    for k, v in sorted(first_features.items()):
                        print(f"  {k}: {v:.6f}")
            result.rows_written = len(enriched_df)
        else:
            try:
                rows = self.writer.write(
                    enriched_df,
                    source=self.provider.source_name,
                    trade_date=trade_date_str,
                    interval="1d",
                )
                result.rows_written = rows
            except Exception as exc:
                error_msg = f"Iceberg write failed: {exc}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        result.duration_seconds = time.time() - start_time
        logger.info(
            "Pipeline complete: %d rows written in %.1fs (errors: %d)",
            result.rows_written,
            result.duration_seconds,
            len(result.errors),
        )

        return result

    @staticmethod
    def _validate(df: pd.DataFrame) -> List[str]:
        """Validate data quality.

        Returns:
            List of validation warning messages (empty if all OK).
        """
        errors: List[str] = []

        # Check for null prices
        for col in ["open", "high", "low", "close"]:
            null_count = df[col].isna().sum()
            if null_count > 0:
                errors.append(f"{null_count} null values in '{col}'")

        # Check for negative prices
        for col in ["open", "high", "low", "close"]:
            neg_count = (df[col].dropna() < 0).sum()
            if neg_count > 0:
                errors.append(f"{neg_count} negative values in '{col}'")

        # Check high >= low
        invalid = (df["high"].dropna() < df["low"].dropna()).sum()
        if invalid > 0:
            errors.append(f"{invalid} rows where high < low")

        return errors


def main():
    """CLI entry point for local pipeline testing."""
    parser = argparse.ArgumentParser(
        description="Market data ingestion pipeline",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compute without writing to Iceberg",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Override symbol list (e.g., HSBA.L BP.L)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default=None,
        help="Universe name (e.g., ftse_100)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    symbols = args.symbols
    if symbols is None and args.universe:
        symbols = SymbolUniverse.get_universe(args.universe)

    pipeline = MarketDataPipeline()
    result = pipeline.run(
        target_date=target_date,
        symbols=symbols,
        dry_run=args.dry_run,
    )

    print(f"\n{'=' * 40}")
    print(f"Pipeline {'SUCCEEDED' if result.success else 'FAILED'}")
    print(f"  Date:           {result.trade_date}")
    print(f"  Source:          {result.source}")
    print(f"  Symbols:         {result.symbols_received}/{result.symbols_requested}")
    print(f"  Rows written:    {result.rows_written}")
    print(f"  Features/row:    ~{result.features_computed}")
    print(f"  Duration:        {result.duration_seconds:.1f}s")
    if result.errors:
        print(f"  Errors:          {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")
    print(f"{'=' * 40}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
