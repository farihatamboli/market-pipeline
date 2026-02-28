"""
tests/test_signals.py — Unit tests for the signal detector.

Hiring managers love seeing tests. These cover the core logic cleanly.
Run with: pytest tests/
"""

import pytest
from datetime import datetime, timedelta
from src.fetcher import Tick
from src.signals import SignalDetector, SignalType


def make_tick(symbol="AAPL", price=150.0, volume=100_000, high=151.0, low=149.0, vwap=150.0, offset_minutes=0):
    return Tick(
        symbol=symbol,
        timestamp=datetime(2024, 1, 15, 14, 30) + timedelta(minutes=offset_minutes),
        price=price,
        volume=volume,
        open=price,
        high=high,
        low=low,
        vwap=vwap,
    )


def make_history(n=20, base_price=150.0, base_volume=100_000, noise=0.1):
    """Generate history ticks with small price noise so stdev > 0."""
    import random
    random.seed(42)
    return [
        make_tick(
            price=base_price + random.uniform(-noise, noise),
            volume=base_volume,
            offset_minutes=i
        )
        for i in range(n)
    ]


class TestPriceSpike:
    def test_no_signal_on_stable_prices(self):
        detector = SignalDetector()
        history = make_history(20, base_price=150.0)
        tick = make_tick(price=150.5, offset_minutes=20)
        history.append(tick)
        signals = detector.detect(tick, history)
        price_signals = [s for s in signals if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(price_signals) == 0

    def test_fires_on_large_spike(self):
        detector = SignalDetector(price_spike_zscore=2.0)
        history = make_history(20, base_price=150.0)
        tick = make_tick(price=165.0, offset_minutes=20)  # large spike
        history.append(tick)
        signals = detector.detect(tick, history)
        price_signals = [s for s in signals if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(price_signals) == 1
        assert price_signals[0].symbol == "AAPL"
        assert "above" in price_signals[0].message

    def test_fires_on_negative_spike(self):
        detector = SignalDetector(price_spike_zscore=2.0)
        history = make_history(20, base_price=150.0)
        tick = make_tick(price=135.0, offset_minutes=20)
        history.append(tick)
        signals = detector.detect(tick, history)
        price_signals = [s for s in signals if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(price_signals) == 1
        assert "below" in price_signals[0].message


class TestVolumeSurge:
    def test_no_signal_on_normal_volume(self):
        detector = SignalDetector()
        history = make_history(20, base_volume=100_000)
        tick = make_tick(volume=120_000, offset_minutes=20)
        history.append(tick)
        signals = detector.detect(tick, history)
        vol_signals = [s for s in signals if s.signal_type == SignalType.VOLUME_SURGE]
        assert len(vol_signals) == 0

    def test_fires_on_volume_surge(self):
        detector = SignalDetector(volume_surge_multiplier=3.0)
        history = make_history(20, base_volume=100_000)
        tick = make_tick(volume=400_000, offset_minutes=20)
        history.append(tick)
        signals = detector.detect(tick, history)
        vol_signals = [s for s in signals if s.signal_type == SignalType.VOLUME_SURGE]
        assert len(vol_signals) == 1
        assert vol_signals[0].metadata["ratio"] >= 3.0


class TestVWAPDeviation:
    def test_no_signal_near_vwap(self):
        detector = SignalDetector(vwap_deviation_pct=0.5)
        history = make_history(20)
        tick = make_tick(price=150.1, vwap=150.0, offset_minutes=20)
        history.append(tick)
        signals = detector.detect(tick, history)
        vwap_signals = [s for s in signals if s.signal_type == SignalType.VWAP_DEVIATION]
        assert len(vwap_signals) == 0

    def test_fires_on_large_vwap_deviation(self):
        detector = SignalDetector(vwap_deviation_pct=0.5)
        history = make_history(20)
        tick = make_tick(price=152.0, vwap=150.0, offset_minutes=20)  # 1.33% above VWAP
        history.append(tick)
        signals = detector.detect(tick, history)
        vwap_signals = [s for s in signals if s.signal_type == SignalType.VWAP_DEVIATION]
        assert len(vwap_signals) == 1


class TestMinHistory:
    def test_no_signals_below_min_history(self):
        detector = SignalDetector(min_history=10)
        history = make_history(5)  # Only 5 ticks
        tick = make_tick(price=200.0, volume=1_000_000, offset_minutes=5)
        history.append(tick)
        signals = detector.detect(tick, history)
        assert signals == []
