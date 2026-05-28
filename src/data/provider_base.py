"""Abstract base class for market data providers.

All data providers must implement this interface. The `source_name` property
is used as the `source` column value in the Iceberg table, allowing multiple
providers to be unioned onto the same table with different source flags.

To add a new provider:
    1. Create a new module (e.g., alpha_vantage_provider.py)
    2. Subclass MarketDataProvider
    3. Implement fetch_daily() returning OHLCV DataFrame
    4. Register in config.yaml and pipeline.py
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import List

import pandas as pd


class MarketDataProvider(ABC):
    """Abstract base class for market data providers.

    Each provider fetches OHLCV data from a specific source and returns
    a standardised DataFrame. The `source` column allows multiple providers
    to coexist in the same Iceberg table.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this data source.

        Used as the `source` column value in the Iceberg table.
        Examples: 'yfinance', 'alpha_vantage', 'polygon', 'ibkr'
        """
        ...

    @abstractmethod
    def fetch_daily(
        self,
        symbols: List[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV data for the given symbols and date range.

        Args:
            symbols: List of ticker symbols (e.g., ['HSBA.L', 'BP.L']).
            start: Start date (inclusive).
            end: End date (inclusive).

        Returns:
            DataFrame with columns:
                - timestamp (datetime64): Market close timestamp.
                - symbol (str): Ticker symbol.
                - open (float): Opening price.
                - high (float): High price.
                - low (float): Low price.
                - close (float): Closing price.
                - adj_close (float): Adjusted closing price.
                - volume (int): Trading volume.

            Returns an empty DataFrame if no data is available
            (e.g., weekends, holidays).

        Raises:
            ConnectionError: If the data source is unreachable.
            ValueError: If symbols list is empty.
        """
        ...
