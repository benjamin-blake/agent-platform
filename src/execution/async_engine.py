"""Async trading execution engine with compute-latency weight penalties."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Trade representation."""

    symbol: str
    signal: float
    size: float
    timestamp: datetime
    execution_time: float = 0.0  # Time to compute and execute
    latency_penalty: float = 0.0  # Penalty applied due to latency


@dataclass
class ExecutionMetrics:
    """Execution performance metrics."""

    total_trades: int = 0
    avg_compute_time: float = 0.0
    avg_latency_penalty: float = 0.0
    compute_time_percentiles: Dict[int, float] = field(default_factory=dict)
    recent_compute_times: List[float] = field(default_factory=list)

    def update(self, compute_time: float, latency_penalty: float):
        """Update metrics with new execution."""
        self.total_trades += 1
        self.recent_compute_times.append(compute_time)

        # Keep only last 100 compute times
        if len(self.recent_compute_times) > 100:
            self.recent_compute_times = self.recent_compute_times[-100:]

        # Update averages
        self.avg_compute_time = np.mean(self.recent_compute_times)
        self.avg_latency_penalty = (self.avg_latency_penalty * (self.total_trades - 1) + latency_penalty) / self.total_trades

        # Update percentiles
        if len(self.recent_compute_times) >= 10:
            self.compute_time_percentiles = {
                50: np.percentile(self.recent_compute_times, 50),
                90: np.percentile(self.recent_compute_times, 90),
                99: np.percentile(self.recent_compute_times, 99),
            }


class LatencyPenaltyCalculator:
    """Calculate penalties based on compute latency."""

    def __init__(
        self,
        max_acceptable_latency: float = 0.1,  # 100ms
        penalty_scale: float = 2.0,
    ):
        """
        Initialize penalty calculator.

        Args:
            max_acceptable_latency: Latency threshold in seconds
            penalty_scale: Scale factor for penalty calculation
        """
        self.max_acceptable_latency = max_acceptable_latency
        self.penalty_scale = penalty_scale

    def calculate_penalty(self, compute_time: float) -> float:
        """
        Calculate penalty based on compute time.

        Penalty increases exponentially with latency beyond threshold.

        Args:
            compute_time: Time taken to compute signal (seconds)

        Returns:
            Penalty multiplier (0 to 1, where 1 = no penalty)
        """
        if compute_time <= self.max_acceptable_latency:
            return 1.0

        excess_latency = compute_time - self.max_acceptable_latency
        penalty = np.exp(-self.penalty_scale * excess_latency)

        return max(0.0, min(1.0, penalty))


class ExecutionEngine:
    """Async execution engine with latency-aware position sizing."""

    def __init__(self, signal_generator: Callable, max_position_size: float = 1000.0, latency_threshold: float = 0.1):
        """
        Initialize execution engine.

        Args:
            signal_generator: Async function that generates trading signals
            max_position_size: Maximum position size per trade
            latency_threshold: Latency threshold for penalties
        """
        self.signal_generator = signal_generator
        self.max_position_size = max_position_size
        self.penalty_calculator = LatencyPenaltyCalculator(latency_threshold)
        self.metrics = ExecutionMetrics()
        self.running = False

    async def compute_signal_with_timing(self, symbol: str, features: Dict[str, float]) -> Tuple[float, float]:
        """
        Compute signal and measure computation time.

        Args:
            symbol: Trading symbol
            features: Market features

        Returns:
            Tuple of (signal, compute_time)
        """
        start_time = time.perf_counter()
        signal = await self.signal_generator(symbol, features)
        compute_time = time.perf_counter() - start_time

        return signal, compute_time

    def apply_latency_penalty(self, signal: float, compute_time: float) -> Tuple[float, float]:
        """
        Apply latency penalty to signal strength.

        Args:
            signal: Raw trading signal
            compute_time: Time taken to compute signal

        Returns:
            Tuple of (adjusted_signal, penalty_factor)
        """
        penalty_factor = self.penalty_calculator.calculate_penalty(compute_time)
        adjusted_signal = signal * penalty_factor

        return adjusted_signal, penalty_factor

    def calculate_position_size(self, signal: float) -> float:
        """
        Calculate position size based on signal strength.

        Args:
            signal: Trading signal (-1 to 1)

        Returns:
            Position size
        """
        return abs(signal) * self.max_position_size

    async def execute_trade(self, symbol: str, features: Dict[str, float]) -> Optional[Trade]:
        """
        Execute single trade with latency penalty.

        Args:
            symbol: Trading symbol
            features: Market features

        Returns:
            Trade object or None if no trade executed
        """
        # Compute signal with timing
        raw_signal, compute_time = await self.compute_signal_with_timing(symbol, features)

        # Apply latency penalty
        adjusted_signal, penalty_factor = self.apply_latency_penalty(raw_signal, compute_time)

        # Update metrics
        latency_penalty = 1.0 - penalty_factor
        self.metrics.update(compute_time, latency_penalty)

        # Calculate position size
        position_size = self.calculate_position_size(adjusted_signal)

        # Execute if signal is strong enough
        if abs(adjusted_signal) > 0.1:  # Minimum threshold
            trade = Trade(
                symbol=symbol,
                signal=adjusted_signal,
                size=position_size,
                timestamp=datetime.now(),
                execution_time=compute_time,
                latency_penalty=latency_penalty,
            )
            return trade

        return None

    async def trading_loop(self, market_data_stream: asyncio.Queue, trade_output: asyncio.Queue, interval: float = 1.0):
        """
        Main async trading loop.

        Args:
            market_data_stream: Queue of incoming market data
            trade_output: Queue for outgoing trades
            interval: Loop interval in seconds
        """
        self.running = True
        consecutive_failures = 0

        while self.running:
            try:
                # Get market data (non-blocking with timeout)
                try:
                    market_data = await asyncio.wait_for(market_data_stream.get(), timeout=interval)
                except asyncio.TimeoutError:
                    await asyncio.sleep(interval)
                    continue

                # Extract symbol and features
                symbol = market_data.get("symbol")
                features = market_data.get("features", {})

                if not symbol:
                    continue

                # Execute trade
                trade = await self.execute_trade(symbol, features)

                if trade:
                    await trade_output.put(trade)

                # Reset failure counter on successful iteration
                consecutive_failures = 0

                # Small delay to prevent CPU spinning
                await asyncio.sleep(0.001)

            except (KeyboardInterrupt, SystemExit):
                raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                logger.error("Trading loop error (failure %d/5): %s", consecutive_failures, e)
                if consecutive_failures >= 5:
                    logger.critical("Trading loop stopped after 5 consecutive failures")
                    break
                await asyncio.sleep(interval)

    def stop(self):
        """Stop the trading loop."""
        self.running = False

    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics."""
        return {
            "total_trades": self.metrics.total_trades,
            "avg_compute_time_ms": self.metrics.avg_compute_time * 1000,
            "avg_latency_penalty": self.metrics.avg_latency_penalty,
            "compute_time_percentiles_ms": {k: v * 1000 for k, v in self.metrics.compute_time_percentiles.items()},
        }


async def run_trading_system(
    signal_generator: Callable, market_data_source: Callable, max_position_size: float = 1000.0, latency_threshold: float = 0.1
):
    """
    Run complete trading system.

    Args:
        signal_generator: Async function to generate signals
        market_data_source: Async function to provide market data
        max_position_size: Maximum position size
        latency_threshold: Latency threshold for penalties
    """
    # Create queues
    market_data_queue = asyncio.Queue(maxsize=100)
    trade_queue = asyncio.Queue(maxsize=100)

    # Create execution engine
    engine = ExecutionEngine(signal_generator, max_position_size, latency_threshold)

    # Start tasks
    data_task = asyncio.create_task(market_data_source(market_data_queue))
    trading_task = asyncio.create_task(engine.trading_loop(market_data_queue, trade_queue, interval=0.1))

    # Process trades
    async def process_trades():
        while True:
            trade = await trade_queue.get()
            print(
                f"Executed trade: {trade.symbol} signal={trade.signal:.4f} "
                f"size={trade.size:.2f} latency={trade.execution_time * 1000:.2f}ms "
                f"penalty={trade.latency_penalty:.4f}"
            )

    trade_task = asyncio.create_task(process_trades())

    # Run until cancelled
    try:
        await asyncio.gather(data_task, trading_task, trade_task)
    except asyncio.CancelledError:
        engine.stop()
        print(f"Final metrics: {engine.get_metrics()}")
