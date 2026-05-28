"""Tests for the market data pipeline."""

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.data.feature_engine import FeatureEngine
from src.data.pipeline import MarketDataPipeline, PipelineResult
from src.data.provider_base import MarketDataProvider
from src.data.universe import SymbolUniverse
from src.data.writer import IcebergWriter
from src.data.yfinance_provider import YFinanceProvider

pytestmark = pytest.mark.unit


# ─── Fixtures ─────────────────────────────────────────────────────────


def _make_ohlcv(symbols=None, days=30) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    symbols = symbols or ["HSBA.L", "BP.L"]
    rows = []
    base_date = pd.Timestamp("2026-02-01")

    for symbol in symbols:
        price = 100.0
        for day in range(days):
            ts = base_date + pd.Timedelta(days=day)
            change = np.random.randn() * 2
            o = price
            h = price + abs(np.random.randn() * 1.5)
            low = price - abs(np.random.randn() * 1.5)
            c = price + change
            price = c  # carry forward

            rows.append(
                {
                    "timestamp": ts,
                    "symbol": symbol,
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(low, 2),
                    "close": round(c, 2),
                    "adj_close": round(c, 2),
                    "volume": int(np.random.uniform(1e6, 5e6)),
                }
            )

    return pd.DataFrame(rows)


class MockProvider(MarketDataProvider):
    """Mock provider that returns fixture data."""

    @property
    def source_name(self) -> str:
        return "mock"

    def fetch_daily(self, symbols, start, end):
        return _make_ohlcv(symbols, days=1)


class MockWriter(IcebergWriter):
    """Mock writer that tracks writes without hitting S3/Iceberg."""

    def __init__(self):
        super().__init__()
        self.written_dfs = []
        self.total_rows = 0

    def write(self, df, source, trade_date=None, interval="1d"):
        self.written_dfs.append(df)
        self.total_rows += len(df)
        return len(df)


# ─── YFinanceProvider Tests ───────────────────────────────────────────


class TestYFinanceProvider:
    def test_source_name(self):
        provider = YFinanceProvider()
        assert provider.source_name == "yfinance"

    def test_fetch_daily_empty_symbols_raises(self):
        provider = YFinanceProvider()
        with pytest.raises(ValueError, match="must not be empty"):
            provider.fetch_daily([], date(2026, 3, 1), date(2026, 3, 1))

    @patch("src.data.yfinance_provider.yf.download")
    def test_fetch_daily_returns_correct_columns(self, mock_download):
        """Test that normalisation produces the expected columns."""
        # Mock single-ticker return
        mock_data = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [105.0],
                "Low": [99.0],
                "Close": [103.0],
                "Adj Close": [103.0],
                "Volume": [1000000],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2026-03-20")]),
        )
        mock_download.return_value = mock_data

        provider = YFinanceProvider(retry_attempts=1)
        result = provider.fetch_daily(["HSBA.L"], date(2026, 3, 20), date(2026, 3, 20))

        expected_cols = ["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
        assert list(result.columns) == expected_cols
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "HSBA.L"
        assert result.iloc[0]["close"] == 103.0

    @patch("src.data.yfinance_provider.yf.download")
    def test_fetch_daily_empty_returns_empty_df(self, mock_download):
        """Test graceful handling when no data returned."""
        mock_download.return_value = pd.DataFrame()

        provider = YFinanceProvider(retry_attempts=1, retry_delay_seconds=0)
        result = provider.fetch_daily(["FAKE.L"], date(2026, 3, 20), date(2026, 3, 20))

        assert result.empty


# ─── SymbolUniverse Tests ─────────────────────────────────────────────


class TestSymbolUniverse:
    def test_ftse_100_not_empty(self):
        symbols = SymbolUniverse.get_ftse_100()
        assert len(symbols) > 0

    def test_ftse_100_all_have_l_suffix(self):
        symbols = SymbolUniverse.get_ftse_100()
        for s in symbols:
            assert s.endswith(".L"), f"{s} doesn't end with .L"

    def test_get_universe_ftse(self):
        symbols = SymbolUniverse.get_universe("ftse_100")
        assert len(symbols) > 50

    def test_get_universe_custom(self):
        symbols = SymbolUniverse.get_universe("custom", ["AAPL", "MSFT"])
        assert symbols == ["AAPL", "MSFT"]

    def test_get_universe_custom_without_tickers_raises(self):
        with pytest.raises(ValueError, match="custom_tickers must be provided"):
            SymbolUniverse.get_universe("custom")

    def test_get_universe_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown universe"):
            SymbolUniverse.get_universe("nasdaq_100")


# ─── Pipeline Orchestrator Tests ──────────────────────────────────────


class TestMarketDataPipeline:
    def test_run_end_to_end_with_mocks(self):
        """Full pipeline with mock provider and writer."""
        writer = MockWriter()
        pipeline = MarketDataPipeline(
            provider=MockProvider(),
            feature_engine=FeatureEngine(technicals=True, sentiment=False, fundamentals=False),
            writer=writer,
        )

        result = pipeline.run(
            target_date=date(2026, 3, 20),
            symbols=["HSBA.L", "BP.L"],
            dry_run=False,
        )

        assert isinstance(result, PipelineResult)
        assert result.source == "mock"
        assert result.symbols_received == 2
        assert result.rows_written > 0
        assert writer.total_rows > 0

    def test_run_dry_run_does_not_write(self):
        """Dry run should not call writer."""
        writer = MockWriter()
        pipeline = MarketDataPipeline(
            provider=MockProvider(),
            feature_engine=FeatureEngine(technicals=True, sentiment=False, fundamentals=False),
            writer=writer,
        )

        result = pipeline.run(
            target_date=date(2026, 3, 20),
            symbols=["HSBA.L"],
            dry_run=True,
        )

        assert result.rows_written > 0  # counts what would have been written
        assert writer.total_rows == 0  # but writer was never called

    def test_pipeline_idempotent_re_run(self):
        """Running twice for the same date doesn't duplicate via writer mock."""
        writer = MockWriter()
        pipeline = MarketDataPipeline(
            provider=MockProvider(),
            feature_engine=FeatureEngine(technicals=True, sentiment=False, fundamentals=False),
            writer=writer,
        )

        result1 = pipeline.run(target_date=date(2026, 3, 20), symbols=["HSBA.L"])
        result2 = pipeline.run(target_date=date(2026, 3, 20), symbols=["HSBA.L"])

        assert result1.rows_written == result2.rows_written
        # Each run calls write once
        assert len(writer.written_dfs) == 2


# ─── PipelineResult Tests ────────────────────────────────────────────


class TestPipelineResult:
    def test_success_when_rows_written(self):
        r = PipelineResult(
            trade_date="2026-03-20",
            source="yfinance",
            symbols_requested=100,
            symbols_received=97,
            rows_written=97,
            features_computed=18,
        )
        assert r.success is True

    def test_failure_when_errors_present(self):
        r = PipelineResult(
            trade_date="2026-03-20",
            source="yfinance",
            symbols_requested=100,
            symbols_received=0,
            rows_written=0,
            features_computed=0,
            errors=["fetch failed"],
        )
        assert r.success is False
