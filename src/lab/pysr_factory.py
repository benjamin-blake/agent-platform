"""PySR factory for symbolic regression and formula discovery."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import botocore.exceptions
import numpy as np
import pandas as pd
import sympy

try:
    import awswrangler as wr
    from awswrangler.exceptions import ServiceApiError as _WranglerServiceApiError
except ImportError:  # pragma: no cover
    wr = None  # type: ignore[assignment]  # optional: available in Lambda layer and local dev

    class _WranglerServiceApiError(Exception):  # type: ignore[no-redef]
        pass


from ..common.config import config
from ..common.database import AthenaClient

logger = logging.getLogger(__name__)

# Lazy-loaded on first call to discover_formulas -- avoids juliapkg network call at module
# import time. Keep the name at module level so patch("src.lab.pysr_factory.PySRRegressor")
# works in tests.
PySRRegressor: Any = None


def _load_pysrregressor() -> None:
    global PySRRegressor
    if PySRRegressor is None:
        from pysr import PySRRegressor as _cls  # noqa: PLC0415

        PySRRegressor = _cls


class FormulaFactory:
    """Factory for discovering trading formulas using symbolic regression."""

    def __init__(self, athena_client: AthenaClient = None):
        """Initialize formula factory."""
        self.athena = athena_client or AthenaClient(workgroup=config.athena_lab_workgroup)

    def fetch_training_data(self, query: str) -> pd.DataFrame:
        """Fetch training data from Athena."""
        execution_id = self.athena.execute_query(query)
        results = self.athena.get_query_results(execution_id)

        # Parse results into DataFrame
        rows = results["Rows"]
        if len(rows) < 2:
            return pd.DataFrame()

        # Extract column names from first row
        columns = [col["VarCharValue"] for col in rows[0]["Data"]]

        # Extract data rows
        data = []
        for row in rows[1:]:
            data.append([col.get("VarCharValue", "") for col in row["Data"]])

        return pd.DataFrame(data, columns=columns)

    def fetch_training_data_from_iceberg(
        self,
        symbols: List[str] = None,
        lookback_days: int = 252,
    ) -> pd.DataFrame:
        """Fetch training data from the market_data Iceberg table.

        Constructs an Athena query that unnests the features map into
        individual columns and computes next-day return as the target.

        Args:
            symbols: Filter to these symbols (default: all).
            lookback_days: How many days of history to use.

        Returns:
            DataFrame with feature columns and a 'target' column
            (next-day return).
        """
        glue_db = config.glue_database

        symbol_filter = ""
        if symbols:
            quoted = ", ".join(f"'{s}'" for s in symbols)
            symbol_filter = f"AND symbol IN ({quoted})"

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
            {symbol_filter}
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

        return self.fetch_training_data(query)

    def discover_formulas(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str] = None,
        niterations: int = 100,
        binary_operators: List[str] = None,
        unary_operators: List[str] = None,
        **kwargs,
    ) -> Any:
        """
        Discover formulas using PySR symbolic regression.

        Args:
            X: Feature matrix
            y: Target variable
            feature_names: Names of features
            niterations: Number of iterations for PySR
            binary_operators: Binary operators to use
            unary_operators: Unary operators to use
            **kwargs: Additional PySR parameters

        Returns:
            Fitted PySR model
        """
        _load_pysrregressor()
        if binary_operators is None:
            binary_operators = ["+", "-", "*", "/"]

        if unary_operators is None:
            unary_operators = ["exp", "log", "abs", "square"]

        model = PySRRegressor(
            niterations=niterations,
            binary_operators=binary_operators,
            unary_operators=unary_operators,
            feature_names=feature_names,
            model_selection="best",
            **kwargs,
        )

        model.fit(X, y)
        return model

    def backtest_formula(self, formula: str, data: pd.DataFrame, initial_capital: float = 100000.0) -> Dict[str, float]:
        """
        Backtest a trading formula.

        Args:
            formula: Trading formula as string
            data: Historical market data
            initial_capital: Starting capital

        Returns:
            Dictionary of performance metrics
        """
        # Simple backtest implementation
        positions = []

        # Note: This uses sympy for safe formula evaluation.
        # Never use eval() — sympy.sympify + lambdify is safe and sandboxed.
        for idx, row in data.iterrows():
            try:
                safe_vars = {k: v for k, v in row.to_dict().items() if isinstance(v, (int, float))}
                expr = sympy.sympify(formula)
                func = sympy.lambdify(
                    list(expr.free_symbols),
                    expr,
                    modules=["numpy"],
                )
                # Map symbol names to values
                sym_vals = {}
                for sym in expr.free_symbols:
                    name = str(sym)
                    if name in safe_vars:
                        sym_vals[sym] = safe_vars[name]
                    else:
                        sym_vals[sym] = 0.0
                signal = float(func(**{str(s): sym_vals[s] for s in expr.free_symbols}))
                positions.append(signal)
            except (ValueError, TypeError, sympy.SympifyError, KeyError) as e:
                logger.warning("Formula evaluation failed for row %s: %s", idx, e)
                positions.append(0)

        positions = np.array(positions)
        returns = data["returns"].values if "returns" in data.columns else np.zeros(len(data))

        # Calculate metrics
        strategy_returns = positions[:-1] * returns[1:]

        total_return = np.sum(strategy_returns)
        sharpe_ratio = np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-9) * np.sqrt(252)

        # Calculate max drawdown
        cumulative = np.cumsum(strategy_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_drawdown = np.min(drawdown)

        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "num_trades": int(np.sum(np.abs(np.diff(positions)) > 0)),
        }

    def save_results_to_athena(self, formula_id: str, formula: str, metrics: Dict[str, float]):
        """Save backtest results to the backtest_results Iceberg table.

        Uses awswrangler MERGE upsert via Athena — consistent with the
        data pipeline's IcebergWriter approach (no PyIceberg dependency).
        """
        try:
            now = datetime.now(timezone.utc)
            df = pd.DataFrame(
                [
                    {
                        "formula_id": formula_id or str(uuid.uuid4()),
                        "formula": formula,
                        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                        "total_return": metrics.get("total_return", 0.0),
                        "max_drawdown": metrics.get("max_drawdown", 0.0),
                        "created_at": now,
                    }
                ]
            )

            s3_bucket = config.get("aws.s3_data_lake_bucket", "")
            workgroup = config.athena_lab_workgroup

            wr.athena.to_iceberg(
                df=df,
                database=config.glue_database,
                table="backtest_results",
                temp_path=f"s3://{s3_bucket}/athena/iceberg-temp/",
                s3_output=f"s3://{s3_bucket}/athena/query-results/",
                workgroup=workgroup,
                merge_cols=["formula_id"],
                keep_files=False,
                schema_evolution=True,
            )
        except (botocore.exceptions.ClientError, _WranglerServiceApiError) as exc:
            logger.error("Failed to save results for %s: %s", formula_id, exc)


class FormulaDiscoveryPipeline:
    """End-to-end pipeline for formula discovery and backtesting."""

    def __init__(self):
        """Initialize pipeline."""
        self.factory = FormulaFactory()

    def run(self, query: str, target_column: str, feature_columns: List[str], niterations: int = 100) -> List[Dict[str, Any]]:
        """
        Run complete discovery and backtest pipeline.

        Args:
            query: Athena query to fetch training data
            target_column: Name of target column
            feature_columns: Names of feature columns
            niterations: PySR iterations

        Returns:
            List of discovered formulas with metrics
        """
        # Fetch data
        data = self.factory.fetch_training_data(query)

        if data.empty:
            return []

        # Prepare features and target
        X = data[feature_columns].astype(float).values
        y = data[target_column].astype(float).values

        # Discover formulas
        model = self.factory.discover_formulas(X, y, feature_names=feature_columns, niterations=niterations)

        # Get best formulas
        results = []
        for idx, row in model.equations_.iterrows():
            formula_str = str(row["equation"])

            # Backtest
            metrics = self.factory.backtest_formula(formula_str, data)

            results.append(
                {
                    "formula_id": f"formula_{idx}",
                    "formula": formula_str,
                    "complexity": row["complexity"],
                    "loss": row["loss"],
                    **metrics,
                }
            )

        return results
