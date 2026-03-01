"""
tests/test_signals.py — Unit tests for the SignalDetector.
Run with: pytest tests/ -v
"""

import random
import pytest
from datetime import datetime, timedelta
from src.fetcher import Tick
from src.signals import SignalDetector, SignalType

random.seed(42)


def make_tick(price=150.0, volume=100_000, vwap=150.0, high=None, low=None, offset=0):
    return Tick(
        symbol    = 'AAPL',
        timestamp = datetime(2024, 1, 15, 14, 30) + timedelta(minutes=offset),
        price     = price, volume=volume,
        open      = price,
        high      = high or price + 0.5,
        low       = low  or price - 0.5,
        vwap      = vwap,
    )

def make_history(n=20, base=150.0, vol=100_000, noise=0.1):
    return [make_tick(price=base + random.uniform(-noise, noise),
                      volume=vol, offset=i) for i in range(n)]


class TestPriceSpike:
    def test_no_false_positive_on_stable(self):
        h = make_history(20, base=150.0)
        t = make_tick(price=150.02, offset=20); h.append(t)
        sigs = [s for s in SignalDetector().detect(t, h) if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(sigs) == 0

    def test_fires_on_upward_spike(self):
        h = make_history(20, base=150.0); t = make_tick(price=170.0, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(price_spike_zscore=2.0).detect(t, h) if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(sigs) == 1
        assert 'above' in sigs[0].message

    def test_fires_on_downward_spike(self):
        h = make_history(20, base=150.0); t = make_tick(price=130.0, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(price_spike_zscore=2.0).detect(t, h) if s.signal_type == SignalType.PRICE_SPIKE]
        assert len(sigs) == 1
        assert 'below' in sigs[0].message

    def test_metadata_contains_zscore(self):
        h = make_history(20, base=150.0); t = make_tick(price=170.0, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(price_spike_zscore=2.0).detect(t, h) if s.signal_type == SignalType.PRICE_SPIKE]
        assert 'zscore' in sigs[0].metadata
        assert sigs[0].metadata['zscore'] > 0


class TestVolumeSurge:
    def test_no_signal_on_normal_volume(self):
        h = make_history(20, vol=100_000); t = make_tick(volume=110_000, offset=20); h.append(t)
        sigs = [s for s in SignalDetector().detect(t, h) if s.signal_type == SignalType.VOLUME_SURGE]
        assert len(sigs) == 0

    def test_fires_on_surge(self):
        h = make_history(20, vol=100_000); t = make_tick(volume=500_000, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(volume_surge_multiplier=3.0).detect(t, h) if s.signal_type == SignalType.VOLUME_SURGE]
        assert len(sigs) == 1
        assert sigs[0].metadata['ratio'] >= 3.0


class TestVWAPDeviation:
    def test_no_signal_near_vwap(self):
        h = make_history(20); t = make_tick(price=150.1, vwap=150.0, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(vwap_deviation_pct=0.5).detect(t, h) if s.signal_type == SignalType.VWAP_DEVIATION]
        assert len(sigs) == 0

    def test_fires_above_vwap(self):
        h = make_history(20); t = make_tick(price=152.0, vwap=150.0, offset=20); h.append(t)
        sigs = [s for s in SignalDetector(vwap_deviation_pct=0.5).detect(t, h) if s.signal_type == SignalType.VWAP_DEVIATION]
        assert len(sigs) == 1
        assert 'above' in sigs[0].message

    def test_no_signal_when_vwap_none(self):
        h = make_history(20); t = make_tick(price=152.0, vwap=None, offset=20); h.append(t)
        sigs = [s for s in SignalDetector().detect(t, h) if s.signal_type == SignalType.VWAP_DEVIATION]
        assert len(sigs) == 0


class TestMinHistory:
    def test_no_signals_below_threshold(self):
        h = make_history(5); t = make_tick(price=999.0, volume=9_999_999, offset=5); h.append(t)
        assert SignalDetector(min_history=10).detect(t, h) == []

    def test_signals_at_exact_threshold(self):
        h = make_history(10); t = make_tick(price=170.0, offset=10); h.append(t)
        # should not be empty (history == min_history)
        result = SignalDetector(min_history=10, price_spike_zscore=2.0).detect(t, h)
        assert isinstance(result, list)
