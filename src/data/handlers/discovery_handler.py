"""Lambda handler: Trigger PySR formula discovery (optional step).

Step Functions state: TriggerDiscovery
Input:  { "date": "2026-03-21", "rows_written": 97, "source": "yfinance" }
Output: { "date": "2026-03-21", "discovery_triggered": true, "formulas_found": 5 }

This step is gated by a Choice state and only runs when
discovery_enabled=true in the Step Functions input or config.
"""

import logging

from src.common.config import config
from src.lab.pysr_factory import FormulaDiscoveryPipeline

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for TriggerDiscovery step.

    Args:
        event: Output from WriteToIceberg step.
        context: Lambda context.

    Returns:
        Dict with discovery results.
    """
    target_date_str = event["date"]

    if event.get("is_empty", False) or event.get("rows_written", 0) == 0:
        logger.info("No data was written — skipping discovery")
        return {
            "date": target_date_str,
            "discovery_triggered": False,
            "formulas_found": 0,
        }

    logger.info("TriggerDiscovery: date=%s", target_date_str)

    glue_db = config.glue_database
    lookback_days = config.get("lab.backtest_period_days", 252)

    # Athena query to fetch training data from the market_data Iceberg table.
    # Unnests the features map into individual columns for PySR consumption.
    # Uses next-day return as the target variable.
    query = f"""
    WITH market AS (
        SELECT
            timestamp,
            symbol,
            close,
            features,
            LEAD(close) OVER (PARTITION BY symbol ORDER BY timestamp) AS next_close
        FROM {glue_db}.market_data
        WHERE trade_date >= CURRENT_DATE - INTERVAL '{lookback_days}' DAY
          AND (interval = '1d' OR interval IS NULL)
    ),
    with_target AS (
        SELECT
            timestamp,
            symbol,
            close,
            features,
            (next_close - close) / close AS next_day_return
        FROM market
        WHERE next_close IS NOT NULL
    )
    SELECT
        timestamp,
        symbol,
        next_day_return AS target,
        features['tech_rsi_14'] AS rsi_14,
        features['tech_macd'] AS macd,
        features['tech_macd_signal'] AS macd_signal,
        features['tech_bb_width'] AS bb_width,
        features['tech_atr_14'] AS atr_14,
        features['tech_momentum_5d'] AS momentum_5d,
        features['tech_momentum_10d'] AS momentum_10d,
        features['tech_momentum_20d'] AS momentum_20d,
        features['tech_volatility_20d'] AS volatility_20d,
        features['tech_volume_ratio'] AS volume_ratio,
        features['sentiment_fear_greed'] AS fear_greed
    FROM with_target
    ORDER BY timestamp
    """

    feature_columns = [
        "rsi_14",
        "macd",
        "macd_signal",
        "bb_width",
        "atr_14",
        "momentum_5d",
        "momentum_10d",
        "momentum_20d",
        "volatility_20d",
        "volume_ratio",
        "fear_greed",
    ]

    pipeline = FormulaDiscoveryPipeline()
    results = pipeline.run(
        query=query,
        target_column="target",
        feature_columns=feature_columns,
        niterations=config.get("lab.pysr_iterations", 100),
    )

    formulas_found = len(results) if results else 0
    logger.info("Discovery complete: %d formulas found", formulas_found)

    # Log top formulas
    if results:
        for r in sorted(results, key=lambda x: x.get("sharpe_ratio", 0), reverse=True)[:3]:
            logger.info(
                "  Formula: %s | Sharpe: %.4f | Complexity: %d",
                r.get("formula", "?"),
                r.get("sharpe_ratio", 0),
                r.get("complexity", 0),
            )

    return {
        "date": target_date_str,
        "discovery_triggered": True,
        "formulas_found": formulas_found,
    }
