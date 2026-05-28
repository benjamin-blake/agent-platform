"""Main entry point for the trading system.

Supports two environments:
- company: Formula discovery on company VM with SageMaker/Athena
- personal: Live trading on personal computer with Docker

Usage:
    python -m src.main --environment=company lab
    python -m src.main --environment=personal live
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Dict

import numpy as np

from src.common.config import config
from src.execution.async_engine import run_trading_system
from src.live.rat_ensemble import RATEnsemble

# Environment constants
ENVIRONMENT_COMPANY = "company"
ENVIRONMENT_PERSONAL = "personal"
VALID_ENVIRONMENTS = [ENVIRONMENT_COMPANY, ENVIRONMENT_PERSONAL]


def detect_environment() -> str:
    """Auto-detect environment based on configuration files.

    Returns:
        str: Detected environment ("company" or "personal")

    Raises:
        RuntimeError: If environment cannot be detected
    """
    config_dir = Path(__file__).parent.parent / "config"

    # Check if TRADING_ENVIRONMENT is explicitly set
    env_var = os.environ.get("TRADING_ENVIRONMENT", "").lower()
    if env_var in VALID_ENVIRONMENTS:
        return env_var

    # Check if TRADING_CONFIG points to a specific config
    config_path = os.environ.get("TRADING_CONFIG", "")
    if config_path:
        if "company" in config_path.lower():
            return ENVIRONMENT_COMPANY
        if "personal" in config_path.lower():
            return ENVIRONMENT_PERSONAL

    # Check which config files exist
    company_config = config_dir / "config.company.yaml"
    personal_config = config_dir / "config.personal.yaml"

    company_exists = company_config.exists()
    personal_exists = personal_config.exists()

    if company_exists and not personal_exists:
        return ENVIRONMENT_COMPANY
    if personal_exists and not company_exists:
        return ENVIRONMENT_PERSONAL

    # If both exist, prefer personal for safety (less cost)
    if company_exists and personal_exists:
        print("Warning: Both config files found, defaulting to 'personal' environment")
        print("  Set TRADING_ENVIRONMENT or use --environment flag to override")
        return ENVIRONMENT_PERSONAL

    raise RuntimeError(
        "Cannot detect environment. Please:\n"
        "  1. Create config.company.yaml or config.personal.yaml in config/\n"
        "  2. Or set TRADING_ENVIRONMENT=company/personal\n"
        "  3. Or use --environment=company/personal flag"
    )


def validate_environment(environment: str, mode: str) -> None:
    """Validate that mode is compatible with environment.

    Args:
        environment: "company" or "personal"
        mode: "lab" or "live"

    Raises:
        ValueError: If mode is incompatible with environment
    """
    if mode == "lab" and environment != ENVIRONMENT_COMPANY:
        raise ValueError(
            "Lab mode (formula discovery) requires company environment.\n"
            "  SageMaker and Athena are only available on company AWS.\n"
            "  Use: --environment=company lab"
        )

    if mode == "live" and environment != ENVIRONMENT_PERSONAL:
        print(
            "Warning: Running live mode on company environment.\n"
            "  This is unusual - live trading typically runs on personal computer.\n"
            "  Press Ctrl+C to cancel or wait 5 seconds to continue...\n"
        )
        import time

        time.sleep(5)


def load_environment_config(environment: str) -> None:
    """Load configuration for specified environment.

    Args:
        environment: "company" or "personal"
    """
    config_dir = Path(__file__).parent.parent / "config"
    config_file = config_dir / f"config.{environment}.yaml"

    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}\n  Create it from config.yaml.example")

    # Set environment variable for config module to load
    os.environ["TRADING_CONFIG"] = str(config_file)
    os.environ["TRADING_ENVIRONMENT"] = environment

    print(f"✓ Loaded {environment} environment configuration")
    print(f"  Config: {config_file}")


async def mock_signal_generator(symbol: str, features: Dict[str, float]) -> float:
    """Mock signal generator for demo purposes."""
    # Simulate some computation time
    await asyncio.sleep(0.01)

    # Simple momentum-based signal
    momentum = features.get("momentum", 0.0)
    return np.tanh(momentum)


async def mock_market_data_source(queue: asyncio.Queue):
    """Mock market data source for demo purposes."""
    symbols = ["AAPL", "GOOGL", "MSFT", "AMZN"]

    while True:
        for symbol in symbols:
            # Generate random market features
            market_data = {
                "symbol": symbol,
                "features": {
                    "momentum": np.random.randn() * 0.5,
                    "price_deviation": np.random.randn() * 0.3,
                    "volume_ratio": np.random.uniform(0.5, 2.0),
                },
            }

            await queue.put(market_data)
            await asyncio.sleep(0.1)


def run_lab_mode():
    """Run formula discovery in lab mode (company environment only)."""
    print("\n=== Lab Mode: Formula Discovery ===")
    print("Environment: Company VM")
    print("Resources: SageMaker, Athena, S3")
    print()

    # Lazy import to avoid Julia download on startup
    from src.lab.pysr_factory import FormulaDiscoveryPipeline

    pipeline = FormulaDiscoveryPipeline()

    # Feature columns from the market_data Iceberg table (via features map)
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

    # Query that unnests features from the Iceberg market_data table
    lookback_days = config.get("lab.backtest_period_days", 252)
    query = f"""
    WITH market AS (
        SELECT
            timestamp,
            symbol,
            close,
            features,
            LEAD(close) OVER (PARTITION BY symbol ORDER BY timestamp) AS next_close
        FROM {config.glue_database}.market_data
        WHERE trade_date >= CURRENT_DATE - INTERVAL '{lookback_days}' DAY
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

    print(f"Athena Workgroup: {config.athena_lab_workgroup}")
    print(f"Glue Database: {config.glue_database}")
    print(f"Output S3 Bucket: {config.s3_formulas_discovery_bucket}")
    print(f"Lookback: {lookback_days} days")
    print(f"Features: {', '.join(feature_columns)}")
    print()
    print("Starting formula discovery...")
    print("Note: This will incur SageMaker compute costs (~$1-5 per run)")
    print()

    results = pipeline.run(
        query=query,
        target_column="target",
        feature_columns=feature_columns,
        niterations=config.get("lab.pysr_iterations", 100),
    )

    if results:
        print(f"\nDiscovered {len(results)} formulas:")
        for result in sorted(results, key=lambda x: x.get("sharpe_ratio", 0), reverse=True):
            print(f"  Formula:     {result['formula']}")
            print(f"  Sharpe:      {result.get('sharpe_ratio', 0):.4f}")
            print(f"  Complexity:  {result.get('complexity', 0)}")
            print(f"  Total Return: {result.get('total_return', 0):.4f}")
            print()
    else:
        print("No formulas discovered — check data availability in market_data table")


async def run_live_mode():
    """Run live trading mode with RAT ensemble (personal environment)."""
    print("\n=== Live Mode: RAT Ensemble Trading ===")
    print("Environment: Personal Computer")
    print("Data Source: Company S3 (read-only)")
    print("Strategy: Formula RAT Models + Meta-Learner")
    print()

    # Create RAT ensemble (loads formulas from PostgreSQL)
    ensemble = RATEnsemble()

    # Create signal generator that uses ensemble
    async def signal_gen(symbol: str, features: Dict[str, float]) -> float:
        """Generate trading signal using RAT ensemble."""
        signal, metadata = ensemble.predict(features, symbol, top_k=10)

        # Log ensemble decision
        if metadata:
            print(f"[{symbol}] Signal: {signal:.4f}")
            print(f"  Active Formulas: {metadata.get('num_models', 0)}")
            print(f"  Confidence: {metadata.get('confidence', 0.0):.4f}")

        return signal

    print("Starting trading system...")
    print(f"Max Position Size: ${config.get('trading.max_position_size', 1000.0):.2f}")
    print(f"Latency Threshold: {config.get('trading.latency_threshold', 0.1):.3f}s")
    print()

    # Run trading system
    try:
        await run_trading_system(
            signal_generator=signal_gen,
            market_data_source=mock_market_data_source,
            max_position_size=config.get("trading.max_position_size", 1000.0),
            latency_threshold=config.get("trading.latency_threshold", 0.1),
        )
    except KeyboardInterrupt:
        print("\nTrading system stopped gracefully.")
    except Exception as e:
        print(f"\nError: {e}")
        raise


def main():
    """Main entry point with environment detection."""
    parser = argparse.ArgumentParser(
        description="Machine Learning Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Company VM - Formula Discovery
  python -m src.main --environment=company lab

  # Personal Computer - Live Trading
  python -m src.main --environment=personal live

  # Auto-detect environment
  python -m src.main live

Environments:
  company  : Formula discovery on company VM (SageMaker/Athena)
  personal : Live trading on personal computer (Docker)
        """,
    )

    parser.add_argument("mode", choices=["lab", "live"], help="Operating mode (lab=discovery, live=trading)")

    parser.add_argument(
        "--environment", choices=VALID_ENVIRONMENTS, help="Environment to run in (auto-detected if not specified)"
    )

    parser.add_argument("--config", type=str, help="Path to configuration file (overrides auto-detection)")

    args = parser.parse_args()

    try:
        # Determine environment
        if args.environment:
            environment = args.environment
        else:
            environment = detect_environment()

        print("\n=== Trading System ===")
        print(f"Environment: {environment}")
        print(f"Mode: {args.mode}")
        print()

        # Validate mode is compatible with environment
        validate_environment(environment, args.mode)

        # Load configuration
        if args.config:
            os.environ["TRADING_CONFIG"] = args.config
        else:
            load_environment_config(environment)

        # Run requested mode
        if args.mode == "lab":
            run_lab_mode()
        elif args.mode == "live":
            asyncio.run(run_live_mode())

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
