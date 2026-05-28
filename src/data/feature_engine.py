# complexity-waiver: decision-43
"""Feature computation engine for market data enrichment.

Computes three categories of features from raw OHLCV data:
    1. Technical indicators (RSI, MACD, Bollinger Bands, ATR, SMAs, etc.)
    2. Basic sentiment (CNN Fear & Greed Index)
    3. Fundamentals (P/E ratio, market cap, dividend yield)
    4. Pre-calculated deltas (momentum, volatility, z-scores, sentiment velocity)

All stable features are written as native top-level columns on the DataFrame
for fast Athena predicate-pushdown and efficient PySR formula discovery.
The `features` map<string,double> column is retained as a landing zone for
experimental data sources that have not yet been promoted to native columns.

Feature naming convention:
    tech_<indicator>      — technical indicators
    sentiment_<source>    — sentiment scores
    fundamental_<metric>  — fundamental data
    delta_<metric>        — pre-calculated momentum / rate-of-change
    zscore_<metric>       — z-score normalised values
"""

import logging
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Module-level cache for Fear & Greed Index — process-specific, 5-minute TTL.
# Acceptable for Lambda/script use; long-running services would need external cache.
_fear_greed_cache: dict = {}
_FEAR_GREED_CACHE_TTL = 300  # 5 minutes


class FeatureEngine:
    """Computes features from raw OHLCV data.

    Each feature category can be enabled/disabled independently via config.
    Stable features are written as native DataFrame columns and also mirrored
    into the `features` map column for backward compatibility.

    When `historical_df` is supplied to `compute()`, delta and z-score columns
    are populated using the combined lookback window.  Without historical data
    these columns will be NaN (acceptable for the first daily run; populated
    correctly once backfill provides sufficient history).
    """

    # Lookback window required for the longest rolling calculation (zscore_30d)
    DELTA_LOOKBACK_DAYS = 35

    def __init__(
        self,
        technicals: bool = True,
        sentiment: bool = True,
        fundamentals: bool = True,
    ):
        """Initialise the feature engine.

        Args:
            technicals: Compute technical indicators.
            sentiment: Fetch and attach sentiment scores.
            fundamentals: Fetch and attach fundamental data.
        """
        self._technicals = technicals
        self._sentiment = sentiment
        self._fundamentals = fundamentals

    def compute(
        self,
        ohlcv: pd.DataFrame,
        historical_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Compute all enabled features and attach as native columns.

        Args:
            ohlcv: Raw OHLCV DataFrame with columns:
                   timestamp, symbol, open, high, low, close, adj_close, volume.
            historical_df: Optional prior rows from the Iceberg market_data table
                           (columns: symbol, timestamp, close, volume, features).
                           Used to compute delta and z-score columns that require
                           a rolling lookback window.  Must cover at least
                           DELTA_LOOKBACK_DAYS before the earliest date in ohlcv.

        Returns:
            The input DataFrame with native feature columns and a `features` map
            column (for backward compatibility and experimental sources).
        """
        if ohlcv.empty:
            ohlcv["features"] = pd.Series(dtype="object")
            return ohlcv

        # Process each symbol independently (indicators need per-symbol history)
        groups: List[pd.DataFrame] = []
        for symbol, group in ohlcv.groupby("symbol", sort=False):
            group = group.sort_values("timestamp").copy()
            hist = None
            if historical_df is not None and not historical_df.empty:
                hist = historical_df[historical_df["symbol"] == symbol].sort_values("timestamp").copy()
            group = self._compute_for_symbol(group, str(symbol), hist)
            groups.append(group)

        result = pd.concat(groups, ignore_index=True)
        return result

    # ------------------------------------------------------------------
    # Per-symbol computation
    # ------------------------------------------------------------------

    def _compute_for_symbol(
        self,
        df: pd.DataFrame,
        symbol: str,
        historical_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Compute features for a single symbol's time series."""
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        features_list: List[Dict[str, float]] = [{} for _ in range(len(df))]

        if self._technicals:
            self._add_technicals(features_list, close, high, low, volume)

        if self._sentiment:
            self._add_sentiment(features_list)

        if self._fundamentals:
            self._add_fundamentals(features_list, symbol)

        # Expand the features dict into individual native columns.
        # This promotes each key (e.g. "tech_rsi_14") to a top-level column
        # so Athena can predicate-push and PySR can access native types directly.
        if features_list:
            features_df = pd.DataFrame(features_list, index=df.index)
            for col in features_df.columns:
                df[col] = features_df[col]

        # Retain the features map as a landing zone for experimental sources.
        df["features"] = [{str(k): float(v) for k, v in d.items() if v is not None} for d in features_list]

        # Add delta / z-score columns using historical lookback.
        self._add_deltas(df, historical_df)

        return df

    # ------------------------------------------------------------------
    # Delta / z-score columns (require historical lookback)
    # ------------------------------------------------------------------

    def _add_deltas(
        self,
        df: pd.DataFrame,
        historical_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """Compute and attach delta / z-score columns.

        Prepends optional historical rows to build the rolling window, then
        assigns only the values corresponding to `df`'s rows.  All columns
        are written as NaN when there is insufficient history.

        Args:
            df: Current rows for a single symbol (sorted by timestamp).
            historical_df: Prior rows for the same symbol from Iceberg
                           (columns: timestamp, close, volume, features or
                           tech_rsi_14, sentiment_fear_greed).
        """
        n_new = len(df)

        # Build combined OHLCV series (historical first, then current).
        if historical_df is not None and not historical_df.empty:
            hist_close = historical_df["close"].astype(float)
            hist_volume = historical_df["volume"].astype(float)

            # Extract RSI from historical — prefer native column, fall back to map.
            if "tech_rsi_14" in historical_df.columns:
                hist_rsi = historical_df["tech_rsi_14"].astype(float)
            elif "features" in historical_df.columns:
                hist_rsi = (
                    historical_df["features"]
                    .apply(lambda d: d.get("tech_rsi_14") if isinstance(d, dict) else None)
                    .astype(float)
                )
            else:
                hist_rsi = pd.Series(dtype=float)

            # Extract sentiment from historical.
            if "sentiment_fear_greed" in historical_df.columns:
                hist_sentiment = historical_df["sentiment_fear_greed"].astype(float)
            elif "features" in historical_df.columns:
                hist_sentiment = (
                    historical_df["features"]
                    .apply(lambda d: d.get("sentiment_fear_greed") if isinstance(d, dict) else None)
                    .astype(float)
                )
            else:
                hist_sentiment = pd.Series(dtype=float)

            close_c = pd.concat(
                [hist_close.reset_index(drop=True), df["close"].astype(float).reset_index(drop=True)],
                ignore_index=True,
            )
            volume_c = pd.concat(
                [hist_volume.reset_index(drop=True), df["volume"].astype(float).reset_index(drop=True)],
                ignore_index=True,
            )
            rsi_c = pd.concat(
                [hist_rsi.reset_index(drop=True), df["tech_rsi_14"].astype(float).reset_index(drop=True)]
                if "tech_rsi_14" in df.columns
                else [hist_rsi.reset_index(drop=True), pd.Series([float("nan")] * n_new)],
                ignore_index=True,
            )
            sentiment_c = pd.concat(
                [hist_sentiment.reset_index(drop=True), df["sentiment_fear_greed"].astype(float).reset_index(drop=True)]
                if "sentiment_fear_greed" in df.columns
                else [hist_sentiment.reset_index(drop=True), pd.Series([float("nan")] * n_new)],
                ignore_index=True,
            )
        else:
            close_c = df["close"].astype(float).reset_index(drop=True)
            volume_c = df["volume"].astype(float).reset_index(drop=True)
            rsi_c = (
                df["tech_rsi_14"].astype(float).reset_index(drop=True)
                if "tech_rsi_14" in df.columns
                else pd.Series([float("nan")] * n_new)
            )
            sentiment_c = (
                df["sentiment_fear_greed"].astype(float).reset_index(drop=True)
                if "sentiment_fear_greed" in df.columns
                else pd.Series([float("nan")] * n_new)
            )

        returns_c = close_c.pct_change()

        # --- Price momentum deltas ---
        for period in [1, 5, 20]:
            delta = close_c.pct_change(periods=period)
            df[f"delta_price_{period}d"] = delta.values[-n_new:]

        # --- Rolling volatility (10-day annualised) ---
        vol_10d = returns_c.rolling(window=10).std() * np.sqrt(252)
        df["delta_volatility_10d"] = vol_10d.values[-n_new:]

        # --- Z-scores (30-day rolling) ---
        mean_30 = close_c.rolling(window=30).mean()
        std_30 = close_c.rolling(window=30).std()
        zscore_close = (close_c - mean_30) / std_30
        df["zscore_close_30d"] = zscore_close.values[-n_new:]

        vol_mean_30 = volume_c.rolling(window=30).mean()
        vol_std_30 = volume_c.rolling(window=30).std()
        zscore_volume = (volume_c - vol_mean_30) / vol_std_30
        df["zscore_volume_30d"] = zscore_volume.values[-n_new:]

        rsi_mean_30 = rsi_c.rolling(window=30).mean()
        rsi_std_30 = rsi_c.rolling(window=30).std()
        zscore_rsi = (rsi_c - rsi_mean_30) / rsi_std_30
        df["zscore_rsi_30d"] = zscore_rsi.values[-n_new:]

        # --- Sentiment velocity (1-day rate of change) ---
        delta_sentiment = sentiment_c.diff(periods=1)
        df["delta_sentiment_1d"] = delta_sentiment.values[-n_new:]

    # ------------------------------------------------------------------
    # Technical indicators
    # ------------------------------------------------------------------

    def _add_technicals(
        self,
        features_list: List[Dict[str, float]],
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        volume: pd.Series,
    ) -> None:
        """Compute and attach technical indicators."""
        n = len(close)

        # --- Returns & momentum ---
        returns = close.pct_change()
        for period in [5, 10, 20]:
            momentum = close.pct_change(periods=period)
            for i in range(n):
                val = momentum.iloc[i]
                if pd.notna(val):
                    features_list[i][f"tech_momentum_{period}d"] = float(val)

        # --- RSI (14) ---
        rsi = self._rsi(close, period=14)
        for i in range(n):
            if pd.notna(rsi.iloc[i]):
                features_list[i]["tech_rsi_14"] = float(rsi.iloc[i])

        # --- MACD (12, 26, 9) ---
        macd_line, signal_line, histogram = self._macd(close)
        for i in range(n):
            if pd.notna(macd_line.iloc[i]):
                features_list[i]["tech_macd"] = float(macd_line.iloc[i])
                features_list[i]["tech_macd_signal"] = float(signal_line.iloc[i])
                features_list[i]["tech_macd_histogram"] = float(histogram.iloc[i])

        # --- Bollinger Band width (20, 2σ) ---
        sma_20 = close.rolling(window=20).mean()
        std_20 = close.rolling(window=20).std()
        bb_width = (2 * std_20) / sma_20
        for i in range(n):
            if pd.notna(bb_width.iloc[i]):
                features_list[i]["tech_bb_width"] = float(bb_width.iloc[i])

        # --- ATR (14) ---
        atr = self._atr(high, low, close, period=14)
        for i in range(n):
            if pd.notna(atr.iloc[i]):
                features_list[i]["tech_atr_14"] = float(atr.iloc[i])

        # --- SMAs (20, 50, 200) ---
        for window in [20, 50, 200]:
            sma = close.rolling(window=window).mean()
            for i in range(n):
                if pd.notna(sma.iloc[i]):
                    features_list[i][f"tech_sma_{window}"] = float(sma.iloc[i])

        # --- EMAs (12, 26) ---
        for span in [12, 26]:
            ema = close.ewm(span=span, adjust=False).mean()
            for i in range(n):
                if pd.notna(ema.iloc[i]):
                    features_list[i][f"tech_ema_{span}"] = float(ema.iloc[i])

        # --- Volume ratio (volume / 20-day average volume) ---
        avg_vol_20 = volume.rolling(window=20).mean()
        vol_ratio = volume / avg_vol_20
        for i in range(n):
            if pd.notna(vol_ratio.iloc[i]):
                features_list[i]["tech_volume_ratio"] = float(vol_ratio.iloc[i])

        # --- Historical volatility (20-day rolling std of returns) ---
        volatility_20 = returns.rolling(window=20).std() * np.sqrt(252)
        for i in range(n):
            if pd.notna(volatility_20.iloc[i]):
                features_list[i]["tech_volatility_20d"] = float(volatility_20.iloc[i])

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def _macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple:
        """MACD line, signal line, and histogram."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range."""
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        return atr

    # ------------------------------------------------------------------
    # Sentiment
    # ------------------------------------------------------------------

    def _add_sentiment(self, features_list: List[Dict[str, float]]) -> None:
        """Fetch and attach sentiment score (CNN Fear & Greed Index).

        The Fear & Greed Index is a market-wide indicator (not per-symbol),
        so the same value is applied to all rows in the batch.

        Falls back gracefully if the API is unavailable.
        """
        fear_greed = self._fetch_fear_greed_index()
        if fear_greed is not None:
            for features in features_list:
                features["sentiment_fear_greed"] = fear_greed

    @staticmethod
    def _fetch_fear_greed_index() -> Optional[float]:
        """Fetch CNN Fear & Greed Index with retry and 5-minute in-process cache.

        Returns:
            Index value (0-100) or None if unavailable.
        """
        now = time.monotonic()
        cached_value = _fear_greed_cache.get("value")
        cached_at = _fear_greed_cache.get("timestamp", 0.0)
        if cached_value is not None and (now - cached_at) < _FEAR_GREED_CACHE_TTL:
            return cached_value

        try:
            import requests

            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {"User-Agent": "Mozilla/5.0"}
            last_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    logger.debug("Fear & Greed Index fetch attempt %d", attempt + 1)
                    resp = requests.get(url, headers=headers, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    score = data.get("fear_and_greed", {}).get("score")
                    if score is not None:
                        result = float(score)
                        _fear_greed_cache["value"] = result
                        _fear_greed_cache["timestamp"] = now
                        return result
                    logger.warning("Malformed response (no score field), retrying...")
                    continue  # Response received but no score — retry
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        time.sleep(1)  # flat 1-second delay between retries
            if last_exc:
                logger.warning("Failed to fetch Fear & Greed Index after 3 attempts: %s", last_exc)
        except ImportError:
            logger.warning("requests not available; Fear & Greed Index not fetched")
        return None

    # ------------------------------------------------------------------
    # Fundamentals
    # ------------------------------------------------------------------

    def _add_fundamentals(self, features_list: List[Dict[str, float]], symbol: str) -> None:
        """Fetch and attach fundamental data from yfinance Ticker.info.

        Fundamentals are fetched once per symbol and applied to all rows
        for that symbol (they don't change day-to-day).

        Falls back gracefully if data is unavailable (e.g., ETFs).
        """
        fundamentals = self._fetch_fundamentals(symbol)
        for features in features_list:
            features.update(fundamentals)

    @staticmethod
    def _fetch_fundamentals(symbol: str) -> Dict[str, float]:
        """Fetch fundamental data from yfinance.

        Returns:
            Dict of fundamental feature values (empty if unavailable).
        """
        result: Dict[str, float] = {}
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info or {}

            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe is not None:
                result["fundamental_pe"] = float(pe)

            mcap = info.get("marketCap")
            if mcap is not None:
                result["fundamental_market_cap"] = float(mcap)

            div_yield = info.get("dividendYield")
            if div_yield is not None:
                result["fundamental_div_yield"] = float(div_yield)

        except Exception as exc:
            logger.warning("Failed to fetch fundamentals for %s: %s", symbol, exc)

        return result
