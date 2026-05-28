"""Data ingestion pipeline for market data.

Provides a modular, extensible pipeline for fetching market data from
multiple sources, computing features, and writing to the Iceberg data lake.

Architecture:
    MarketDataProvider (abstract) → YFinanceProvider, AlphaVantageProvider, ...
    FeatureEngine → computes technicals, sentiment, fundamentals
    IcebergWriter → writes to S3/Iceberg via awswrangler MERGE upsert (zero-maintenance partitioning)
    MarketDataPipeline → orchestrates fetch → compute → validate → write
"""

try:
    from .feature_engine import FeatureEngine
    from .pipeline import MarketDataPipeline
    from .provider_base import MarketDataProvider
    from .universe import SymbolUniverse
    from .writer import IcebergWriter
    from .yfinance_provider import YFinanceProvider

    __all__ = [
        "MarketDataProvider",
        "YFinanceProvider",
        "SymbolUniverse",
        "FeatureEngine",
        "IcebergWriter",
        "MarketDataPipeline",
    ]
except ImportError:
    # Optional heavy dependencies (pandas, numpy, awswrangler) are not
    # available in all Lambda environments (e.g. scheduled-agent handlers).
    # Callers that need these classes must ensure the pandas layer is attached.
    pass
