"""Yahoo Finance market data provider.

Uses the yfinance library to fetch daily OHLCV bars. yfinance has no explicit
rate limit for daily data, but we implement configurable retry/backoff to
handle transient failures gracefully.

FTSE 100 tickers use the .L suffix (e.g., HSBA.L for HSBC).
"""

import logging
import time
from datetime import date, timedelta
from typing import List

import pandas as pd
import yfinance as yf

from .provider_base import MarketDataProvider

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    """Fetches daily OHLCV data from Yahoo Finance.

    Batch-fetches all symbols in a single yfinance.download() call
    to minimise network overhead. Handles weekends/holidays by returning
    an empty DataFrame when no data is available.
    """

    def __init__(self, retry_attempts: int = 3, retry_delay_seconds: int = 60):
        """Initialise the Yahoo Finance provider.

        Args:
            retry_attempts: Number of retries on transient failure.
            retry_delay_seconds: Seconds to wait between retries.
        """
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay_seconds

    @property
    def source_name(self) -> str:
        return "yfinance"

    def fetch_daily(
        self,
        symbols: List[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for all symbols in one batch call.

        Args:
            symbols: Ticker symbols (e.g., ['HSBA.L', 'BP.L']).
            start: Start date (inclusive).
            end: End date (inclusive).

        Returns:
            Standardised DataFrame with columns:
            timestamp, symbol, open, high, low, close, adj_close, volume.
        """
        if not symbols:
            raise ValueError("symbols list must not be empty")

        # yfinance end date is exclusive, so add one day
        end_exclusive = end + timedelta(days=1)

        raw = self._download_with_retry(symbols, start, end_exclusive)

        if raw is None or raw.empty:
            logger.warning("No data returned for %s between %s and %s", symbols, start, end)
            return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"])

        return self._normalise(raw, symbols)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_with_retry(self, symbols: List[str], start: date, end_exclusive: date) -> pd.DataFrame:
        """Download with exponential backoff on transient failures."""
        last_error = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                logger.info(
                    "yfinance download attempt %d/%d for %d symbols (%s → %s)",
                    attempt,
                    self._retry_attempts,
                    len(symbols),
                    start,
                    end_exclusive,
                )

                data = yf.download(
                    tickers=symbols,
                    start=str(start),
                    end=str(end_exclusive),
                    group_by="ticker",
                    auto_adjust=False,
                    threads=True,
                )

                if data is not None and not data.empty:
                    return data

            except Exception as exc:
                last_error = exc
                logger.warning("yfinance download attempt %d failed: %s", attempt, exc)

            if attempt < self._retry_attempts:
                delay = self._retry_delay * attempt
                logger.info("Retrying in %d seconds…", delay)
                time.sleep(delay)

        if last_error:
            logger.error("All %d download attempts failed: %s", self._retry_attempts, last_error)
        return pd.DataFrame()

    @staticmethod
    def _normalise(raw: pd.DataFrame, symbols: List[str]) -> pd.DataFrame:
        """Normalise yfinance multi-ticker output into a flat DataFrame.

        yfinance returns a MultiIndex DataFrame when multiple tickers are
        requested (level 0 = ticker, level 1 = OHLCV column). For a single
        ticker it returns a simple DataFrame with OHLCV columns.

        Raises:
            ValueError: If required columns are missing from yfinance response.
        """
        # Validate input schema
        if raw.empty:
            return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"])
        rows: list[pd.DataFrame] = []

        if len(symbols) == 1:
            # Single-ticker: columns are just OHLCV strings
            symbol = symbols[0]
            df = raw.copy()

            # Validate required columns exist
            required_cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                raise ValueError(f"yfinance response missing required columns: {missing}")

            df["symbol"] = symbol
            df = df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                }
            )
            df["timestamp"] = df.index
            rows.append(df)
        else:
            # Multi-ticker: MultiIndex (ticker, field) columns
            for symbol in symbols:
                try:
                    ticker_data = raw[symbol].copy()
                except KeyError:
                    logger.warning("No data for symbol %s — skipping", symbol)
                    continue

                if ticker_data.dropna(how="all").empty:
                    continue

                ticker_data["symbol"] = symbol
                ticker_data = ticker_data.rename(
                    columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Adj Close": "adj_close",
                        "Volume": "volume",
                    }
                )
                ticker_data["timestamp"] = ticker_data.index
                rows.append(ticker_data)

        if not rows:
            return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"])

        result = pd.concat(rows, ignore_index=True)
        result = result[["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"]]

        # Drop rows where all OHLCV values are NaN (holidays etc.)
        ohlcv_cols = ["open", "high", "low", "close", "volume"]
        result = result.dropna(subset=ohlcv_cols, how="all").reset_index(drop=True)

        return result
