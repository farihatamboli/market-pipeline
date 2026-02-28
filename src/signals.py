"""
signals.py — Detects market anomalies and trading signals from tick data.

Implemented signals:
  1. Price spike      — price moves > N std devs from rolling mean
  2. Volume surge     — volume > N× rolling average
  3. Volatility burst — high-low range expands sharply
  4. VWAP deviation   — price diverges significantly from VWAP

These are the kinds of signals quant shops use in production.
The architecture (stateless detector, history passed in) makes unit testing trivial.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .fetcher import Tick

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    PRICE_SPIKE = "PRICE_SPIKE"
    VOLUME_SURGE = "VOLUME_SURGE"
    VOLATILITY_BURST = "VOLATILITY_BURST"
    VWAP_DEVIATION = "VWAP_DEVIATION"


@dataclass
class Signal:
    """A fired signal with full context for downstream alerting."""
    signal_type: SignalType
    symbol: str
    timestamp: datetime
    price: float
    message: str
    metadata: dict = field(default_factory=dict)

    def __str__(self):
        return f"[{self.signal_type}] {self.symbol} @ {self.price:.2f} — {self.message}"


class SignalDetector:
    """
    Stateless signal detector. Takes a current tick + history window,
    returns a list of fired signals.

    Thresholds are configurable at init time for easy tuning.
    """

    def __init__(
        self,
        price_spike_zscore: float = 2.5,
        volume_surge_multiplier: float = 3.0,
        volatility_burst_multiplier: float = 2.5,
        vwap_deviation_pct: float = 0.5,
        min_history: int = 10,
    ):
        self.price_spike_zscore = price_spike_zscore
        self.volume_surge_multiplier = volume_surge_multiplier
        self.volatility_burst_multiplier = volatility_burst_multiplier
        self.vwap_deviation_pct = vwap_deviation_pct
        self.min_history = min_history

    def detect(self, tick: Tick, history: list[Tick]) -> list[Signal]:
        """
        Run all signal detectors against the current tick.

        Args:
            tick: The latest data point
            history: Recent ticks including the current one (oldest first)

        Returns:
            List of Signal objects (empty if nothing triggered)
        """
        if len(history) < self.min_history:
            logger.debug(f"{tick.symbol}: insufficient history ({len(history)} < {self.min_history}), skipping signals")
            return []

        signals = []

        # Exclude the current tick from history for comparison
        past = history[:-1] if len(history) > 1 else history

        signals.extend(self._check_price_spike(tick, past))
        signals.extend(self._check_volume_surge(tick, past))
        signals.extend(self._check_volatility_burst(tick, past))
        signals.extend(self._check_vwap_deviation(tick))

        return signals

    def _check_price_spike(self, tick: Tick, past: list[Tick]) -> list[Signal]:
        prices = [t.price for t in past]
        if len(prices) < 2:
            return []

        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return []

        zscore = (tick.price - mean) / stdev
        if abs(zscore) >= self.price_spike_zscore:
            direction = "above" if zscore > 0 else "below"
            return [Signal(
                signal_type=SignalType.PRICE_SPIKE,
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                price=tick.price,
                message=f"Price {tick.price:.2f} is {abs(zscore):.2f}σ {direction} rolling mean {mean:.2f}",
                metadata={"zscore": round(zscore, 3), "mean": round(mean, 4), "stdev": round(stdev, 4)},
            )]
        return []

    def _check_volume_surge(self, tick: Tick, past: list[Tick]) -> list[Signal]:
        volumes = [t.volume for t in past if t.volume > 0]
        if not volumes:
            return []

        avg_vol = statistics.mean(volumes)
        if avg_vol == 0:
            return []

        ratio = tick.volume / avg_vol
        if ratio >= self.volume_surge_multiplier:
            return [Signal(
                signal_type=SignalType.VOLUME_SURGE,
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                price=tick.price,
                message=f"Volume {tick.volume:,} is {ratio:.1f}× average ({avg_vol:,.0f})",
                metadata={"ratio": round(ratio, 2), "avg_volume": round(avg_vol)},
            )]
        return []

    def _check_volatility_burst(self, tick: Tick, past: list[Tick]) -> list[Signal]:
        ranges = [t.high - t.low for t in past if t.high and t.low]
        if not ranges:
            return []

        avg_range = statistics.mean(ranges)
        if avg_range == 0:
            return []

        current_range = tick.high - tick.low
        ratio = current_range / avg_range
        if ratio >= self.volatility_burst_multiplier:
            return [Signal(
                signal_type=SignalType.VOLATILITY_BURST,
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                price=tick.price,
                message=f"H-L range ${current_range:.2f} is {ratio:.1f}× average (${avg_range:.2f})",
                metadata={"range": round(current_range, 4), "avg_range": round(avg_range, 4), "ratio": round(ratio, 2)},
            )]
        return []

    def _check_vwap_deviation(self, tick: Tick) -> list[Signal]:
        if tick.vwap is None or tick.vwap == 0:
            return []

        deviation_pct = abs(tick.price - tick.vwap) / tick.vwap * 100
        if deviation_pct >= self.vwap_deviation_pct:
            direction = "above" if tick.price > tick.vwap else "below"
            return [Signal(
                signal_type=SignalType.VWAP_DEVIATION,
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                price=tick.price,
                message=f"Price {tick.price:.2f} is {deviation_pct:.2f}% {direction} VWAP {tick.vwap:.2f}",
                metadata={"deviation_pct": round(deviation_pct, 3), "vwap": tick.vwap},
            )]
        return []
