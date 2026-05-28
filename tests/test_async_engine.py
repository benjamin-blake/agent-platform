"""Tests for async_engine module."""

import asyncio
from unittest.mock import patch

import pytest

from src.execution.async_engine import ExecutionEngine

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_trading_loop_catches_generic_exception():
    """Test that trading_loop catches generic Exception (not just ConnectionError/TimeoutError).

    Verifies that the circuit breaker exception handler catches all exceptions.
    """

    async def dummy_signal_generator():
        return {"symbol": "TEST"}

    engine = ExecutionEngine(
        signal_generator=dummy_signal_generator,
        max_position_size=1000.0,
        latency_threshold=0.1,
    )

    market_data_stream = asyncio.Queue()
    trade_output = asyncio.Queue()

    # Add test data
    await market_data_stream.put({"symbol": "TEST", "features": {}})

    # Patch execute_trade to raise a generic ValueError
    with patch.object(engine, "execute_trade", side_effect=ValueError("Test error")):
        with patch("src.execution.async_engine.logger"):
            engine.running = True
            task = asyncio.create_task(engine.trading_loop(market_data_stream, trade_output, interval=0.001))

            # Let it run briefly
            await asyncio.sleep(0.1)
            engine.stop()

            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
