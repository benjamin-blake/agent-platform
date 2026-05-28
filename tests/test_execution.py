"""Tests for execution engine."""

import asyncio

import numpy as np
import pytest

from src.execution.async_engine import ExecutionEngine, ExecutionMetrics, LatencyPenaltyCalculator

pytestmark = pytest.mark.unit


def test_latency_penalty_calculator():
    """Test latency penalty calculation."""
    calculator = LatencyPenaltyCalculator(max_acceptable_latency=0.1, penalty_scale=2.0)

    # No penalty for fast execution
    assert calculator.calculate_penalty(0.05) == 1.0
    assert calculator.calculate_penalty(0.1) == 1.0

    # Penalty for slow execution
    penalty = calculator.calculate_penalty(0.2)
    assert 0.0 < penalty < 1.0

    # Higher penalty for very slow execution
    penalty_slow = calculator.calculate_penalty(0.5)
    assert penalty_slow < penalty


def test_execution_metrics():
    """Test execution metrics tracking."""
    metrics = ExecutionMetrics()

    # Initial state
    assert metrics.total_trades == 0
    assert metrics.avg_compute_time == 0.0

    # Update metrics
    metrics.update(0.05, 0.0)
    assert metrics.total_trades == 1
    assert metrics.avg_compute_time == 0.05

    metrics.update(0.10, 0.1)
    assert metrics.total_trades == 2
    assert np.isclose(metrics.avg_compute_time, 0.075)


@pytest.mark.asyncio
async def test_execution_engine_signal_computation():
    """Test signal computation with timing."""

    async def mock_signal_generator(symbol, features):
        await asyncio.sleep(0.01)
        return 0.5

    engine = ExecutionEngine(signal_generator=mock_signal_generator, max_position_size=1000.0, latency_threshold=0.1)

    signal, compute_time = await engine.compute_signal_with_timing("TEST", {"momentum": 0.5})

    assert signal == 0.5
    assert compute_time > 0.0


@pytest.mark.asyncio
async def test_execution_engine_trade():
    """Test trade execution."""

    async def mock_signal_generator(symbol, features):
        return features.get("momentum", 0.0)

    engine = ExecutionEngine(signal_generator=mock_signal_generator, max_position_size=1000.0, latency_threshold=0.1)

    # Strong signal should result in trade
    trade = await engine.execute_trade("TEST", {"momentum": 0.8})
    assert trade is not None
    assert trade.symbol == "TEST"
    assert trade.size > 0

    # Weak signal should not result in trade
    trade = await engine.execute_trade("TEST", {"momentum": 0.05})
    assert trade is None


def test_position_sizing():
    """Test position size calculation."""

    async def mock_signal_generator(symbol, features):
        return 0.0

    engine = ExecutionEngine(signal_generator=mock_signal_generator, max_position_size=1000.0)

    # Full position for strong signal
    size = engine.calculate_position_size(1.0)
    assert size == 1000.0

    # Half position for medium signal
    size = engine.calculate_position_size(0.5)
    assert size == 500.0

    # Small position for weak signal
    size = engine.calculate_position_size(0.1)
    assert size == 100.0
