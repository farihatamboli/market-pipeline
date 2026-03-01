"""
src/signals.py — Stateless anomaly detectors.

Stateless design (pure function: tick + history → signals) means:
  - Trivially unit-testable
  - Easy to parallelize across symbols
  - No hidden state bugs

Implemented signals:
  1. PRICE_SPIKE      — price moves > N σ from rolling mean
  2. VOLUME_SURGE     — volume > N× rolling average
  3. VOLATILITY_BURST — H-L range expands sharply
  4. VWAP_DEVIATION   — price diverges from session VWAP
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .fetcher import Tick

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    PRICE_SPIKE       = "PRICE_SPIKE"
    VOLUME_SURGE      = "VOLUME_SURGE"
    VOLATILITY_BURST  = "VOLATILITY_BURST"
    VWAP_DEVIATION    = "VWAP_DEVIATION"


@dataclass
class Signal:
    signal_type: SignalType
    symbol:      str
    timestamp:   datetime
    price:       float
    message:     str
    metadata:    dict = field(default_factory=dict)

    def __str__(self):
        return f"[{self.signal_type}] {self.symbol} @ {self.price:.2f} — {self.message}"


class SignalDetector:

    def __init__(
        self,
        price_spike_zscore:        float = 2.5,
        volume_surge_multiplier:   float = 3.0,
        volatility_burst_multiplier: float = 2.5,
        vwap_deviation_pct:        float = 0.5,
        min_history:               int   = 10,
    ):
        self.price_spike_zscore          = price_spike_zscore
        self.volume_surge_multiplier     = volume_surge_multiplier
        self.volatility_burst_multiplier = volatility_burst_multiplier
        self.vwap_deviation_pct          = vwap_deviation_pct
        self.min_history                 = min_history

    def detect(self, tick: Tick, history: list[Tick]) -> list[Signal]:
        if len(history) < self.min_history:
            return []
        past = history[:-1] if len(history) > 1 else history
        signals = []
        signals.extend(self._check_price_spike(tick, past))
        signals.extend(self._check_volume_surge(tick, past))
        signals.extend(self._check_volatility_burst(tick, past))
        signals.extend(self._check_vwap_deviation(tick))
        return signals

    def _check_price_spike(self, tick, past):
        prices = [t.price for t in past]
        if len(prices) < 2:
            return []
        mean  = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return []
        z = (tick.price - mean) / stdev
        if abs(z) >= self.price_spike_zscore:
            direction = "above" if z > 0 else "below"
            return [Signal(
                signal_type = SignalType.PRICE_SPIKE,
                symbol      = tick.symbol,
                timestamp   = tick.timestamp,
                price       = tick.price,
                message     = f"Price {tick.price:.2f} is {abs(z):.2f}σ {direction} rolling mean {mean:.2f}",
                metadata    = {"zscore": round(z, 3), "mean": round(mean, 4), "stdev": round(stdev, 4)},
            )]
        return []

    def _check_volume_surge(self, tick, past):
        vols = [t.volume for t in past if t.volume > 0]
        if not vols:
            return []
        avg = statistics.mean(vols)
        if avg == 0:
            return []
        ratio = tick.volume / avg
        if ratio >= self.volume_surge_multiplier:
            return [Signal(
                signal_type = SignalType.VOLUME_SURGE,
                symbol      = tick.symbol,
                timestamp   = tick.timestamp,
                price       = tick.price,
                message     = f"Volume {tick.volume:,} is {ratio:.1f}× average ({avg:,.0f})",
                metadata    = {"ratio": round(ratio, 2), "avg_volume": round(avg)},
            )]
        return []

    def _check_volatility_burst(self, tick, past):
        ranges = [t.high - t.low for t in past if t.high and t.low]
        if not ranges:
            return []
        avg = statistics.mean(ranges)
        if avg == 0:
            return []
        cur   = tick.high - tick.low
        ratio = cur / avg
        if ratio >= self.volatility_burst_multiplier:
            return [Signal(
                signal_type = SignalType.VOLATILITY_BURST,
                symbol      = tick.symbol,
                timestamp   = tick.timestamp,
                price       = tick.price,
                message     = f"H-L range ${cur:.2f} is {ratio:.1f}× average (${avg:.2f})",
                metadata    = {"range": round(cur, 4), "avg_range": round(avg, 4), "ratio": round(ratio, 2)},
            )]
        return []

    def _check_vwap_deviation(self, tick):
        if not tick.vwap or tick.vwap == 0:
            return []
        dev = abs(tick.price - tick.vwap) / tick.vwap * 100
        if dev >= self.vwap_deviation_pct:
            direction = "above" if tick.price > tick.vwap else "below"
            return [Signal(
                signal_type = SignalType.VWAP_DEVIATION,
                symbol      = tick.symbol,
                timestamp   = tick.timestamp,
                price       = tick.price,
                message     = f"Price {tick.price:.2f} is {dev:.2f}% {direction} VWAP {tick.vwap:.2f}",
                metadata    = {"deviation_pct": round(dev, 3), "vwap": tick.vwap},
            )]
        return []
