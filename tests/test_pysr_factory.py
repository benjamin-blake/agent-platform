"""Unit tests for src/lab/pysr_factory.py"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from botocore.exceptions import ClientError

from src.common.database import AthenaClient
from src.lab.pysr_factory import FormulaDiscoveryPipeline, FormulaFactory, _WranglerServiceApiError


class TestFormulaFactoryInit:
    """Test FormulaFactory initialization."""

    def test_init_with_default_client(self):
        """Test initialization with default AthenaClient."""
        with patch("src.lab.pysr_factory.AthenaClient") as mock_client:
            factory = FormulaFactory()
            assert factory.athena is not None
            mock_client.assert_called_once()

    def test_init_with_custom_client(self):
        """Test initialization with custom AthenaClient."""
        mock_client = MagicMock(spec=AthenaClient)
        factory = FormulaFactory(athena_client=mock_client)
        assert factory.athena is mock_client


class TestFetchTrainingData:
    """Test fetch_training_data method."""

    def test_fetch_training_data_success(self):
        """Test successful data fetch from Athena."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {
            "Rows": [
                {"Data": [{"VarCharValue": "col1"}, {"VarCharValue": "col2"}]},
                {"Data": [{"VarCharValue": "1.0"}, {"VarCharValue": "2.0"}]},
                {"Data": [{"VarCharValue": "3.0"}, {"VarCharValue": "4.0"}]},
            ]
        }

        factory = FormulaFactory(athena_client=mock_client)
        df = factory.fetch_training_data("SELECT * FROM table")

        assert len(df) == 2, f"Expected 2 rows, got {len(df)}"
        assert list(df.columns) == ["col1", "col2"]
        assert df.iloc[0, 0] == "1.0"
        mock_client.execute_query.assert_called_once_with("SELECT * FROM table")
        mock_client.get_query_results.assert_called_once_with("exec-id-123")

    def test_fetch_training_data_empty_result(self):
        """Test data fetch with no results."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {"Rows": []}

        factory = FormulaFactory(athena_client=mock_client)
        df = factory.fetch_training_data("SELECT * FROM table")

        assert df.empty, "Expected empty DataFrame"

    def test_fetch_training_data_header_only(self):
        """Test data fetch with only header, no data rows."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {"Rows": [{"Data": [{"VarCharValue": "col1"}, {"VarCharValue": "col2"}]}]}

        factory = FormulaFactory(athena_client=mock_client)
        df = factory.fetch_training_data("SELECT * FROM table")

        assert df.empty, "Expected empty DataFrame with only header"

    def test_fetch_training_data_missing_varcharvalue(self):
        """Test handling of missing VarCharValue fields."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {
            "Rows": [
                {"Data": [{"VarCharValue": "col1"}, {"VarCharValue": "col2"}]},
                {"Data": [{"VarCharValue": "1.0"}, {}]},
            ]
        }

        factory = FormulaFactory(athena_client=mock_client)
        df = factory.fetch_training_data("SELECT * FROM table")

        assert len(df) == 1, f"Expected 1 row, got {len(df)}"
        assert df.iloc[0, 1] == ""


class TestFetchTrainingDataFromIceberg:
    """Test fetch_training_data_from_iceberg method."""

    def test_fetch_from_iceberg_all_symbols(self):
        """Test fetching data for all symbols."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {
            "Rows": [
                {
                    "Data": [
                        {"VarCharValue": "timestamp"},
                        {"VarCharValue": "symbol"},
                        {"VarCharValue": "target"},
                        {"VarCharValue": "rsi_14"},
                    ]
                },
                {
                    "Data": [
                        {"VarCharValue": "2026-01-01"},
                        {"VarCharValue": "AAPL"},
                        {"VarCharValue": "0.01"},
                        {"VarCharValue": "50.0"},
                    ]
                },
            ]
        }

        factory = FormulaFactory(athena_client=mock_client)
        df = factory.fetch_training_data_from_iceberg()

        assert len(df) == 1, f"Expected 1 row, got {len(df)}"
        mock_client.execute_query.assert_called_once()
        call_args = mock_client.execute_query.call_args[0][0]
        assert "market_data" in call_args
        assert "next_day_return" in call_args
        assert "CURRENT_DATE - INTERVAL '252' DAY" in call_args

    def test_fetch_from_iceberg_filtered_symbols(self):
        """Test fetching data for specific symbols."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {"Rows": []}

        factory = FormulaFactory(athena_client=mock_client)
        factory.fetch_training_data_from_iceberg(symbols=["AAPL", "GOOGL"], lookback_days=100)

        call_args = mock_client.execute_query.call_args[0][0]
        assert "symbol IN ('AAPL', 'GOOGL')" in call_args
        assert "CURRENT_DATE - INTERVAL '100' DAY" in call_args

    def test_fetch_from_iceberg_custom_lookback(self):
        """Test fetching data with custom lookback period."""
        mock_client = MagicMock(spec=AthenaClient)
        mock_client.execute_query.return_value = "exec-id-123"
        mock_client.get_query_results.return_value = {"Rows": []}

        factory = FormulaFactory(athena_client=mock_client)
        factory.fetch_training_data_from_iceberg(lookback_days=30)

        call_args = mock_client.execute_query.call_args[0][0]
        assert "INTERVAL '30' DAY" in call_args


class TestDiscoverFormulas:
    """Test discover_formulas method."""

    def test_discover_formulas_success(self):
        """Test successful formula discovery."""
        X = np.array([[1, 2], [3, 4], [5, 6]])
        y = np.array([3, 7, 11])

        mock_model = MagicMock()
        mock_model.fit.return_value = None

        with patch("src.lab.pysr_factory.PySRRegressor", return_value=mock_model):
            factory = FormulaFactory(athena_client=MagicMock())
            result = factory.discover_formulas(X, y, feature_names=["x", "y"])

            assert result is mock_model
            mock_model.fit.assert_called_once()
            call_args = mock_model.fit.call_args
            np.testing.assert_array_equal(call_args[0][0], X)
            np.testing.assert_array_equal(call_args[0][1], y)

    def test_discover_formulas_default_operators(self):
        """Test formula discovery with default operators."""
        X = np.array([[1, 2], [3, 4]])
        y = np.array([3, 7])

        mock_model = MagicMock()
        with patch("src.lab.pysr_factory.PySRRegressor") as mock_class:
            mock_class.return_value = mock_model
            factory = FormulaFactory(athena_client=MagicMock())
            factory.discover_formulas(X, y)

            call_kwargs = mock_class.call_args[1]
            assert call_kwargs["binary_operators"] == ["+", "-", "*", "/"]
            assert "exp" in call_kwargs["unary_operators"]
            assert "log" in call_kwargs["unary_operators"]

    def test_discover_formulas_custom_operators(self):
        """Test formula discovery with custom operators."""
        X = np.array([[1, 2], [3, 4]])
        y = np.array([3, 7])

        mock_model = MagicMock()
        binary_ops = ["+", "-"]
        unary_ops = ["sin", "cos"]

        with patch("src.lab.pysr_factory.PySRRegressor") as mock_class:
            mock_class.return_value = mock_model
            factory = FormulaFactory(athena_client=MagicMock())
            factory.discover_formulas(
                X,
                y,
                binary_operators=binary_ops,
                unary_operators=unary_ops,
            )

            call_kwargs = mock_class.call_args[1]
            assert call_kwargs["binary_operators"] == binary_ops
            assert call_kwargs["unary_operators"] == unary_ops

    def test_discover_formulas_custom_iterations(self):
        """Test formula discovery with custom iteration count."""
        X = np.array([[1, 2], [3, 4]])
        y = np.array([3, 7])

        mock_model = MagicMock()
        with patch("src.lab.pysr_factory.PySRRegressor") as mock_class:
            mock_class.return_value = mock_model
            factory = FormulaFactory(athena_client=MagicMock())
            factory.discover_formulas(X, y, niterations=250)

            call_kwargs = mock_class.call_args[1]
            assert call_kwargs["niterations"] == 250


class TestBacktestFormula:
    """Test backtest_formula method."""

    def test_backtest_formula_success(self):
        """Test successful formula backtest."""
        data = pd.DataFrame(
            {
                "rsi": [40.0, 50.0, 60.0],
                "returns": [0.01, -0.02, 0.03],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())
        metrics = factory.backtest_formula("rsi * 0.5", data)

        assert "total_return" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert "num_trades" in metrics
        assert isinstance(metrics["total_return"], (int, float))

    def test_backtest_formula_with_multiple_features(self):
        """Test backtest with multiple feature variables."""
        data = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
                "y": [4.0, 5.0, 6.0],
                "returns": [0.01, -0.01, 0.02],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())
        metrics = factory.backtest_formula("x + y", data)

        assert "total_return" in metrics
        assert isinstance(metrics["sharpe_ratio"], (int, float))

    def test_backtest_formula_invalid_formula(self):
        """Test backtest with invalid formula."""
        data = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
                "returns": [0.01, -0.01, 0.02],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())
        metrics = factory.backtest_formula("x / 0", data)

        assert "total_return" in metrics
        # Should not raise, should log warning and handle gracefully

    def test_backtest_formula_missing_returns_column(self):
        """Test backtest when returns column is missing."""
        data = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())
        metrics = factory.backtest_formula("x * 2", data)

        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics

    def test_backtest_formula_missing_variable_in_data(self):
        """Test backtest when formula references missing variables."""
        data = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
                "returns": [0.01, -0.01, 0.02],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())
        metrics = factory.backtest_formula("x + missing_var", data)

        assert "total_return" in metrics
        assert "sharpe_ratio" in metrics

    def test_backtest_formula_arithmetic_operations(self):
        """Test backtest with various arithmetic operations."""
        data = pd.DataFrame(
            {
                "price": [100.0, 101.0, 102.0],
                "returns": [0.01, 0.01, 0.01],
            }
        )

        factory = FormulaFactory(athena_client=MagicMock())

        metrics1 = factory.backtest_formula("price - 100", data)
        metrics2 = factory.backtest_formula("price / 100", data)
        metrics3 = factory.backtest_formula("price * 2", data)

        assert metrics1["total_return"] is not None
        assert metrics2["total_return"] is not None
        assert metrics3["total_return"] is not None


class TestSaveResultsToAthena:
    """Test save_results_to_athena method."""

    def test_save_results_success(self):
        """Test successful save to Athena."""
        mock_client = MagicMock(spec=AthenaClient)

        metrics = {
            "sharpe_ratio": 1.5,
            "total_return": 0.25,
            "max_drawdown": -0.10,
        }

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            with patch("src.lab.pysr_factory.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = "formula-id-123"
                factory = FormulaFactory(athena_client=mock_client)
                factory.save_results_to_athena("formula-123", "x + y", metrics)

                mock_wr.athena.to_iceberg.assert_called_once()
                call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
                assert call_kwargs["table"] == "backtest_results"
                assert call_kwargs["merge_cols"] == ["formula_id"]

    def test_save_results_with_generated_formula_id(self):
        """Test save with auto-generated formula ID."""
        mock_client = MagicMock(spec=AthenaClient)

        metrics = {"sharpe_ratio": 1.0}

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            with patch("src.lab.pysr_factory.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = "auto-id-123"
                factory = FormulaFactory(athena_client=mock_client)
                factory.save_results_to_athena(None, "x + y", metrics)

                call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
                df = call_kwargs["df"]
                assert df.iloc[0]["formula_id"] == "auto-id-123"

    def test_save_results_missing_metrics(self):
        """Test save with missing metrics (should use defaults)."""
        mock_client = MagicMock(spec=AthenaClient)
        metrics = {}

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            factory = FormulaFactory(athena_client=mock_client)
            factory.save_results_to_athena("formula-123", "x", metrics)

            call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
            df = call_kwargs["df"]
            assert df.iloc[0]["sharpe_ratio"] == 0.0
            assert df.iloc[0]["total_return"] == 0.0

    def test_save_results_client_error(self):
        """Test save failure due to ClientError."""
        mock_client = MagicMock(spec=AthenaClient)

        metrics = {"sharpe_ratio": 1.0}

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            mock_wr.athena.to_iceberg.side_effect = ClientError(
                {"Error": {"Code": "ServiceUnavailable"}},
                "PutObject",
            )

            factory = FormulaFactory(athena_client=mock_client)
            # Should not raise, should log error
            factory.save_results_to_athena("formula-123", "x + y", metrics)

    def test_save_results_wrangler_error(self):
        """Test save failure due to awswrangler error."""
        mock_client = MagicMock(spec=AthenaClient)
        metrics = {"sharpe_ratio": 1.0}

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            mock_wr.athena.to_iceberg.side_effect = _WranglerServiceApiError("Service error")

            factory = FormulaFactory(athena_client=mock_client)
            # Should not raise, should log error
            factory.save_results_to_athena("formula-123", "x + y", metrics)

    def test_save_results_timestamp_recorded(self):
        """Test that creation timestamp is recorded."""
        mock_client = MagicMock(spec=AthenaClient)
        metrics = {"sharpe_ratio": 1.0}

        with patch("src.lab.pysr_factory.wr") as mock_wr:
            with patch("src.lab.pysr_factory.datetime") as mock_datetime:
                mock_now = datetime.now(timezone.utc)
                mock_datetime.now.return_value = mock_now
                mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

                factory = FormulaFactory(athena_client=mock_client)
                factory.save_results_to_athena("formula-123", "x + y", metrics)

                call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
                df = call_kwargs["df"]
                assert df.iloc[0]["created_at"] == mock_now


class TestFormulaDiscoveryPipelineInit:
    """Test FormulaDiscoveryPipeline initialization."""

    def test_pipeline_init(self):
        """Test pipeline initialization creates factory."""
        with patch("src.lab.pysr_factory.FormulaFactory"):
            pipeline = FormulaDiscoveryPipeline()
            assert pipeline.factory is not None


class TestFormulaDiscoveryPipelineRun:
    """Test FormulaDiscoveryPipeline.run method."""

    def test_pipeline_run_success(self):
        """Test complete pipeline execution."""
        query = "SELECT * FROM market_data"
        target_column = "target"
        feature_columns = ["rsi", "macd"]

        mock_factory = MagicMock(spec=FormulaFactory)
        mock_data = pd.DataFrame(
            {
                "rsi": [40.0, 50.0, 60.0],
                "macd": [0.1, 0.2, 0.3],
                "target": [0.01, -0.01, 0.02],
            }
        )

        mock_model = MagicMock()
        mock_model.equations_ = pd.DataFrame(
            {
                "equation": ["x + y", "x * y"],
                "complexity": [1, 2],
                "loss": [0.01, 0.005],
            }
        )

        mock_factory.fetch_training_data.return_value = mock_data
        mock_factory.discover_formulas.return_value = mock_model
        mock_factory.backtest_formula.return_value = {
            "total_return": 0.1,
            "sharpe_ratio": 1.5,
            "max_drawdown": -0.05,
            "num_trades": 10,
        }

        with patch("src.lab.pysr_factory.FormulaFactory", return_value=mock_factory):
            pipeline = FormulaDiscoveryPipeline()
            results = pipeline.run(query, target_column, feature_columns)

            assert len(results) == 2
            assert results[0]["formula"] == "x + y"
            assert results[0]["complexity"] == 1
            assert results[0]["total_return"] == 0.1
            assert results[1]["formula"] == "x * y"
            mock_factory.fetch_training_data.assert_called_once_with(query)
            mock_factory.discover_formulas.assert_called_once()

    def test_pipeline_run_empty_data(self):
        """Test pipeline with empty data."""
        query = "SELECT * FROM market_data"
        target_column = "target"
        feature_columns = ["rsi"]

        mock_factory = MagicMock(spec=FormulaFactory)
        mock_factory.fetch_training_data.return_value = pd.DataFrame()

        with patch("src.lab.pysr_factory.FormulaFactory", return_value=mock_factory):
            pipeline = FormulaDiscoveryPipeline()
            results = pipeline.run(query, target_column, feature_columns)

            assert results == []
            mock_factory.discover_formulas.assert_not_called()

    def test_pipeline_run_formula_id_generation(self):
        """Test that formula IDs are generated sequentially."""
        query = "SELECT * FROM data"
        target_column = "target"
        feature_columns = ["x"]

        mock_factory = MagicMock(spec=FormulaFactory)
        mock_data = pd.DataFrame({"x": [1.0, 2.0], "target": [1.0, 4.0]})

        mock_model = MagicMock()
        mock_model.equations_ = pd.DataFrame(
            {
                "equation": ["x", "x**2"],
                "complexity": [1, 2],
                "loss": [0.1, 0.01],
            }
        )

        mock_factory.fetch_training_data.return_value = mock_data
        mock_factory.discover_formulas.return_value = mock_model
        mock_factory.backtest_formula.return_value = {
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "num_trades": 0,
        }

        with patch("src.lab.pysr_factory.FormulaFactory", return_value=mock_factory):
            pipeline = FormulaDiscoveryPipeline()
            results = pipeline.run(query, target_column, feature_columns)

            assert results[0]["formula_id"] == "formula_0"
            assert results[1]["formula_id"] == "formula_1"

    def test_pipeline_run_with_custom_iterations(self):
        """Test pipeline with custom iteration count."""
        query = "SELECT * FROM data"
        target_column = "target"
        feature_columns = ["x"]

        mock_factory = MagicMock(spec=FormulaFactory)
        mock_data = pd.DataFrame({"x": [1.0], "target": [1.0]})
        mock_model = MagicMock()
        mock_model.equations_ = pd.DataFrame(
            {
                "equation": ["x"],
                "complexity": [1],
                "loss": [0.1],
            }
        )

        mock_factory.fetch_training_data.return_value = mock_data
        mock_factory.discover_formulas.return_value = mock_model
        mock_factory.backtest_formula.return_value = {
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "num_trades": 0,
        }

        with patch("src.lab.pysr_factory.FormulaFactory", return_value=mock_factory):
            pipeline = FormulaDiscoveryPipeline()
            pipeline.run(query, target_column, feature_columns, niterations=500)

            call_kwargs = mock_factory.discover_formulas.call_args[1]
            assert call_kwargs["niterations"] == 500

    def test_pipeline_run_datatype_conversion(self):
        """Test that data is converted to proper dtypes for model."""
        query = "SELECT * FROM data"
        target_column = "target"
        feature_columns = ["x", "y"]

        mock_factory = MagicMock(spec=FormulaFactory)
        mock_data = pd.DataFrame(
            {
                "x": ["1.0", "2.0"],
                "y": ["3.0", "4.0"],
                "target": ["0.01", "0.02"],
            }
        )
        mock_model = MagicMock()
        mock_model.equations_ = pd.DataFrame(
            {
                "equation": ["x + y"],
                "complexity": [1],
                "loss": [0.01],
            }
        )

        mock_factory.fetch_training_data.return_value = mock_data
        mock_factory.discover_formulas.return_value = mock_model
        mock_factory.backtest_formula.return_value = {
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "num_trades": 0,
        }

        with patch("src.lab.pysr_factory.FormulaFactory", return_value=mock_factory):
            pipeline = FormulaDiscoveryPipeline()
            pipeline.run(query, target_column, feature_columns)

            call_args = mock_factory.discover_formulas.call_args[0]
            X = call_args[0]
            y = call_args[1]
            assert X.dtype in [np.float32, np.float64]
            assert y.dtype in [np.float32, np.float64]
