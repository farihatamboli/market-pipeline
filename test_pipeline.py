"""
tests/test_pipeline.py — Full pytest test suite for the pipeline.

Coverage targets:
  - Signal detection logic (all 4 detectors)
  - Storage read/write (SQLite)
  - P&L simulator (trades, PnL calculation, reporting)
  - Webhook rate limiting
  - API endpoints
  - TimescaleDB adapter (mocked)
"""

import sys
import time
import random
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fetcher  import Tick
from src.signals  import SignalDetector, SignalType, Signal
from src.storage  import DataStore
from src.pnl_simulator import PnLSimulator, SimConfig, Side


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_tick(
    symbol="AAPL", price=150.0, volume=100_000,
    ts: datetime = None, vwap: float = None,
    high: float = None, low: float = None,
) -> Tick:
    return Tick(
        symbol    = symbol,
        timestamp = ts or datetime.utcnow(),
        price     = price,
        volume    = volume,
        open      = price - 0.5,
        high      = high or price + 0.5,
        low       = low  or price - 0.5,
        vwap      = vwap or price + 0.1,
    )


def make_history(n=30, symbol="AAPL", base=150.0) -> list[Tick]:
    """Generate n ticks with small random walk — no anomalies."""
    ticks, p = [], base
    now = datetime.utcnow()
    for i in range(n):
        p += random.gauss(0, base * 0.001)   # tiny moves
        ticks.append(Tick(
            symbol=symbol, timestamp=now+timedelta(minutes=i),
            price=round(p,4), volume=100_000,
            open=round(p-.1,4), high=round(p+.2,4),
            low=round(p-.2,4), vwap=round(p+.05,4),
        ))
    return ticks


@pytest.fixture
def detector():
    return SignalDetector()


@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    store = DataStore(db_path=db_path)
    store.initialize()
    yield store
    store.close()
    db_path.unlink(missing_ok=True)


# ── Signal Detection ──────────────────────────────────────────────────────────

class TestSignalDetector:

    def test_no_signals_on_flat_data(self, detector):
        """No signals should fire on flat/normal data."""
        history = make_history(30)
        last    = make_tick(price=history[-1].price * 1.0001)  # ~0.01% move
        signals = detector.detect(last, history)
        assert signals == [], f"Expected no signals, got {signals}"

    def test_insufficient_history_returns_empty(self, detector):
        """Fewer than min_periods ticks should suppress all signals."""
        short_history = make_history(3)
        tick          = make_tick(price=999_999)  # absurd price
        signals       = detector.detect(tick, short_history)
        assert signals == []

    def test_price_spike_up(self, detector):
        """A 5σ price spike should trigger PRICE_SPIKE."""
        history = make_history(30, base=150.0)
        prices  = [t.price for t in history]
        mean    = sum(prices) / len(prices)
        std     = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        spike   = make_tick(price=mean + 6 * std)   # 6σ — guaranteed trigger
        signals = detector.detect(spike, history)
        types   = [s.signal_type for s in signals]
        assert SignalType.PRICE_SPIKE in types

    def test_price_spike_down(self, detector):
        """A large downward spike should also trigger PRICE_SPIKE."""
        history = make_history(30, base=150.0)
        prices  = [t.price for t in history]
        mean    = sum(prices) / len(prices)
        std     = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        crash   = make_tick(price=mean - 6 * std)
        signals = detector.detect(crash, history)
        types   = [s.signal_type for s in signals]
        assert SignalType.PRICE_SPIKE in types

    def test_volume_surge(self, detector):
        """10× normal volume should trigger VOLUME_SURGE."""
        history = make_history(30)   # all 100k volume
        surge   = make_tick(volume=10_000_000)  # 100× average
        signals = detector.detect(surge, history)
        types   = [s.signal_type for s in signals]
        assert SignalType.VOLUME_SURGE in types

    def test_volatility_burst(self, detector):
        """An unusually wide H-L range should trigger VOLATILITY_BURST."""
        history = make_history(30)
        # history has tight H-L ranges (~0.4 per tick), give it a massive candle
        wide = make_tick(price=150.0, high=160.0, low=140.0)
        signals = detector.detect(wide, history)
        types   = [s.signal_type for s in signals]
        assert SignalType.VOLATILITY_BURST in types

    def test_vwap_deviation(self, detector):
        """Price 2% above VWAP should trigger VWAP_DEVIATION."""
        tick = make_tick(price=153.0, vwap=150.0)   # +2% above VWAP
        signals = detector.detect(tick, make_history(30))
        types   = [s.signal_type for s in signals]
        assert SignalType.VWAP_DEVIATION in types

    def test_signal_has_required_fields(self, detector):
        """Every signal must have symbol, price, timestamp, message, metadata."""
        history = make_history(30)
        prices  = [t.price for t in history]
        mean    = sum(prices) / len(prices)
        std     = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        spike   = make_tick(price=mean + 6 * std)
        signals = detector.detect(spike, history)
        assert signals, "Expected at least one signal"
        for s in signals:
            assert s.symbol
            assert s.price > 0
            assert isinstance(s.timestamp, datetime)
            assert isinstance(s.message, str) and s.message
            assert isinstance(s.metadata, dict)

    def test_multiple_signals_can_fire(self, detector):
        """A freak tick (huge price spike + huge volume) can trigger multiple signals."""
        history = make_history(30, base=150.0)
        prices  = [t.price for t in history]
        mean    = sum(prices) / len(prices)
        std     = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        freak   = make_tick(price=mean + 7 * std, volume=50_000_000)
        signals = detector.detect(freak, history)
        assert len(signals) >= 2

    def test_detect_is_deterministic(self, detector):
        """Same input → same output (no randomness, no hidden state)."""
        history = make_history(30)
        tick    = make_tick(price=999.0)
        r1 = detector.detect(tick, history)
        r2 = detector.detect(tick, history)
        assert [s.signal_type for s in r1] == [s.signal_type for s in r2]


# ── Storage ───────────────────────────────────────────────────────────────────

class TestDataStore:

    def test_initialize_creates_table(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db.db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        conn.close()
        assert "ticks" in tables

    def test_insert_and_retrieve(self, tmp_db):
        tick = make_tick(symbol="AAPL", price=180.0, volume=500_000)
        tmp_db.insert_tick(tick)
        result = tmp_db.get_recent("AAPL", 10)
        assert len(result) == 1
        assert abs(result[0].price - 180.0) < 0.01

    def test_get_recent_respects_limit(self, tmp_db):
        for i in range(20):
            tmp_db.insert_tick(make_tick(price=100 + i))
        result = tmp_db.get_recent("AAPL", 5)
        assert len(result) == 5

    def test_get_recent_returns_newest(self, tmp_db):
        """get_recent should return the most recent N ticks."""
        now = datetime.utcnow()
        for i in range(10):
            tmp_db.insert_tick(make_tick(
                price=100 + i,
                ts=now + timedelta(minutes=i)
            ))
        result = tmp_db.get_recent("AAPL", 3)
        prices = [r.price for r in result]
        assert max(prices) == pytest.approx(109.0, abs=0.1)

    def test_symbol_isolation(self, tmp_db):
        """Ticks for different symbols must not bleed into each other."""
        tmp_db.insert_tick(make_tick(symbol="AAPL", price=180.0))
        tmp_db.insert_tick(make_tick(symbol="MSFT", price=420.0))
        aapl = tmp_db.get_recent("AAPL", 10)
        msft = tmp_db.get_recent("MSFT", 10)
        assert len(aapl) == 1
        assert len(msft) == 1
        assert aapl[0].symbol == "AAPL"
        assert msft[0].symbol == "MSFT"

    def test_get_symbols(self, tmp_db):
        tmp_db.insert_tick(make_tick(symbol="AAPL"))
        tmp_db.insert_tick(make_tick(symbol="MSFT"))
        tmp_db.insert_tick(make_tick(symbol="NVDA"))
        symbols = tmp_db.get_symbols()
        assert set(symbols) == {"AAPL", "MSFT", "NVDA"}

    def test_concurrent_writes(self, tmp_db):
        """Multiple threads writing simultaneously must not corrupt the DB."""
        errors = []
        def writer(sym, n):
            try:
                for i in range(n):
                    tmp_db.insert_tick(make_tick(symbol=sym, price=100+i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"SYM{i}", 10)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors, f"Concurrent write errors: {errors}"
        total = sum(len(tmp_db.get_recent(f"SYM{i}", 100)) for i in range(5))
        assert total == 50


# ── P&L Simulator ─────────────────────────────────────────────────────────────

class TestPnLSimulator:

    def test_long_trade_profit(self):
        """A long trade that hits take-profit should show positive PnL."""
        cfg = SimConfig(initial_capital=100_000, position_size=0.05,
                        hold_bars=100, stop_loss_pct=0.05, take_profit_pct=0.02)
        sim = PnLSimulator(cfg)
        signal = Signal(
            symbol="AAPL", signal_type=SignalType.VOLUME_SURGE,
            price=100.0, timestamp=datetime.utcnow(), message="test",
            metadata={},
        )
        sim.on_signal(signal)
        assert len(sim.state.open_trades) == 1
        assert sim.state.open_trades[0].side == Side.LONG

        # Push price up past take-profit
        for i in range(3):
            sim.on_tick(make_tick(symbol="AAPL", price=102.5))  # +2.5% > 2% target

        assert len(sim.state.closed_trades) == 1
        assert sim.state.closed_trades[0].pnl > 0
        assert sim.state.closed_trades[0].exit_reason == "TARGET"

    def test_stop_loss_fires(self):
        """A trade that drops past stop-loss must be closed with negative PnL."""
        cfg = SimConfig(initial_capital=100_000, position_size=0.05,
                        hold_bars=100, stop_loss_pct=0.005, take_profit_pct=0.05)
        sim = PnLSimulator(cfg)
        signal = Signal(
            symbol="AAPL", signal_type=SignalType.VOLUME_SURGE,
            price=100.0, timestamp=datetime.utcnow(), message="test", metadata={},
        )
        sim.on_signal(signal)
        sim.on_tick(make_tick(symbol="AAPL", price=99.0))  # -1% > stop 0.5%

        assert len(sim.state.closed_trades) == 1
        assert sim.state.closed_trades[0].exit_reason == "STOP"
        assert sim.state.closed_trades[0].pnl < 0

    def test_hold_bars_exit(self):
        cfg = SimConfig(initial_capital=100_000, position_size=0.05,
                        hold_bars=3, stop_loss_pct=0.99, take_profit_pct=0.99)
        sim = PnLSimulator(cfg)
        sim.on_signal(Signal(
            symbol="AAPL", signal_type=SignalType.VOLUME_SURGE,
            price=100.0, timestamp=datetime.utcnow(), message="t", metadata={},
        ))
        for _ in range(4):
            sim.on_tick(make_tick(symbol="AAPL", price=100.0))

        assert len(sim.state.closed_trades) == 1
        assert sim.state.closed_trades[0].exit_reason == "TIME"

    def test_max_positions_respected(self):
        cfg = SimConfig(max_positions=2)
        sim = PnLSimulator(cfg)
        for sym in ["A","B","C"]:
            sim.on_signal(Signal(
                symbol=sym, signal_type=SignalType.VOLUME_SURGE,
                price=100.0, timestamp=datetime.utcnow(), message="t", metadata={},
            ))
        assert len(sim.state.open_trades) == 2

    def test_report_structure(self):
        cfg = SimConfig(initial_capital=50_000, hold_bars=1,
                        stop_loss_pct=0.99, take_profit_pct=0.01)
        sim = PnLSimulator(cfg)
        sim.on_signal(Signal(
            symbol="AAPL", signal_type=SignalType.VOLUME_SURGE,
            price=100.0, timestamp=datetime.utcnow(), message="t", metadata={},
        ))
        sim.on_tick(make_tick("AAPL", price=101.5))   # take profit
        report = sim.report()
        assert "summary"      in report
        assert "trade_stats"  in report
        assert "risk_metrics" in report
        assert "equity_curve" in report
        assert report["trade_stats"]["total_trades"] == 1

    def test_capital_conservation(self):
        """Capital + open unrealised PnL should stay close to initial after a flat trade."""
        cfg = SimConfig(initial_capital=100_000, position_size=0.05,
                        hold_bars=3, stop_loss_pct=0.99, take_profit_pct=0.99)
        sim = PnLSimulator(cfg)
        sim.on_signal(Signal(
            symbol="AAPL", signal_type=SignalType.VOLUME_SURGE,
            price=100.0, timestamp=datetime.utcnow(), message="t", metadata={},
        ))
        # Flat price — trade closes at TIME with ~0 PnL (minus commission)
        for _ in range(4):
            sim.on_tick(make_tick("AAPL", price=100.0))

        # Allow ~0.1% for commission round-trip
        assert abs(sim.state.capital - 100_000) / 100_000 < 0.001


# ── Webhook rate limiting ─────────────────────────────────────────────────────

class TestWebhookRateLimiter:

    def test_allows_first_call(self):
        from src.webhooks import _RateLimiter
        rl = _RateLimiter(cooldown=10)
        assert rl.allow("AAPL") is True

    def test_blocks_second_call_within_cooldown(self):
        from src.webhooks import _RateLimiter
        rl = _RateLimiter(cooldown=10)
        rl.allow("AAPL")
        assert rl.allow("AAPL") is False

    def test_allows_after_cooldown(self):
        from src.webhooks import _RateLimiter
        rl = _RateLimiter(cooldown=0)  # 0s cooldown
        rl.allow("AAPL")
        time.sleep(0.01)
        assert rl.allow("AAPL") is True

    def test_per_symbol_isolation(self):
        from src.webhooks import _RateLimiter
        rl = _RateLimiter(cooldown=60)
        rl.allow("AAPL")
        assert rl.allow("MSFT") is True  # different symbol — not rate limited

    @patch("src.webhooks._post")
    def test_discord_no_url_skips(self, mock_post):
        from src.webhooks import DiscordChannel
        ch = DiscordChannel(webhook_url="")
        ch.send(Signal(symbol="AAPL", signal_type=SignalType.PRICE_SPIKE,
                       price=100.0, timestamp=datetime.utcnow(), message="test", metadata={}))
        mock_post.assert_not_called()

    @patch("src.webhooks._post", return_value=204)
    def test_discord_sends_embed(self, mock_post):
        from src.webhooks import DiscordChannel
        ch = DiscordChannel(webhook_url="https://discord.example.com/webhook", cooldown=0)
        ch.send(Signal(symbol="AAPL", signal_type=SignalType.PRICE_SPIKE,
                       price=150.0, timestamp=datetime.utcnow(), message="spike!", metadata={"zscore": "3.1"}))
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        assert "embeds" in payload
        assert payload["embeds"][0]["color"] == 0xFF4060

    @patch("src.webhooks._post", return_value=200)
    def test_slack_sends_blocks(self, mock_post):
        from src.webhooks import SlackChannel
        ch = SlackChannel(webhook_url="https://hooks.slack.example.com/T/B/X", cooldown=0)
        ch.send(Signal(symbol="MSFT", signal_type=SignalType.VOLUME_SURGE,
                       price=415.0, timestamp=datetime.utcnow(), message="surge!", metadata={}))
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        assert "blocks" in payload


# ── Benchmark sanity ──────────────────────────────────────────────────────────

class TestPerformance:

    def test_detection_throughput(self, detector):
        """Signal detection should process at least 1000 ticks/sec."""
        history = make_history(50)
        ticks   = make_history(200, base=150.0)

        t0 = time.perf_counter()
        for tick in ticks:
            detector.detect(tick, history)
        elapsed = time.perf_counter() - t0
        tps = len(ticks) / elapsed

        assert tps >= 1000, f"Too slow: {tps:.0f} ticks/sec (need ≥1000)"

    def test_storage_write_latency(self, tmp_db):
        """Each SQLite write should complete in under 50ms."""
        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            tmp_db.insert_tick(make_tick())
            latencies.append((time.perf_counter() - t0) * 1000)

        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        assert p99 < 50, f"P99 write latency {p99:.1f}ms exceeds 50ms"
