"""
src/pnl_simulator.py — Paper trading P&L simulator.

Simulates trading based on detected signals and tracks performance
over time. Useful for evaluating signal quality without real money.

Strategy logic:
  - PRICE_SPIKE (up)  → short entry (mean reversion bet)
  - PRICE_SPIKE (down) → long entry
  - VOLUME_SURGE      → long entry (momentum bet)
  - VWAP_DEVIATION    → fade trade (bet on reversion to VWAP)
  - All positions exit after `hold_bars` ticks or at stop-loss

Usage:
    from src.pnl_simulator import PnLSimulator, SimConfig
    from src.signals import SignalType

    sim = PnLSimulator(SimConfig(
        initial_capital = 100_000,
        position_size   = 0.05,   # 5% of capital per trade
        hold_bars       = 15,     # hold for 15 ticks
        stop_loss_pct   = 0.005,  # 0.5% stop
    ))

    # Feed it ticks and signals from your backtest
    sim.on_tick(tick)
    sim.on_signal(signal)

    report = sim.report()
    print(report)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .fetcher import Tick
from .signals import Signal, SignalType

logger = logging.getLogger(__name__)


class Side(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"


@dataclass
class SimConfig:
    initial_capital: float = 100_000.0
    position_size:   float = 0.05     # fraction of capital per trade
    hold_bars:       int   = 15       # max bars to hold a position
    stop_loss_pct:   float = 0.005    # 0.5% hard stop
    take_profit_pct: float = 0.01     # 1.0% take profit
    commission_pct:  float = 0.0001   # 0.01% per trade (realistic for equities)
    max_positions:   int   = 5        # max concurrent open positions


@dataclass
class Trade:
    symbol:      str
    side:        Side
    entry_price: float
    entry_time:  datetime
    shares:      float
    signal_type: str
    bars_held:   int   = 0
    exit_price:  Optional[float] = None
    exit_time:   Optional[datetime] = None
    pnl:         Optional[float] = None
    exit_reason: str   = ""

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == Side.LONG:
            return (current_price - self.entry_price) * self.shares
        else:
            return (self.entry_price - current_price) * self.shares


@dataclass
class SimState:
    capital:         float
    open_trades:     list[Trade] = field(default_factory=list)
    closed_trades:   list[Trade] = field(default_factory=list)
    equity_curve:    list[dict]  = field(default_factory=list)
    last_prices:     dict        = field(default_factory=dict)


class PnLSimulator:

    def __init__(self, config: SimConfig = None):
        self.cfg   = config or SimConfig()
        self.state = SimState(capital=self.cfg.initial_capital)

    # ── Signal → trade entry logic ────────────────────────────────────────

    def _signal_to_side(self, signal: Signal) -> Optional[Side]:
        """Map a signal type to a trade direction."""
        if signal.signal_type == SignalType.PRICE_SPIKE:
            # Mean reversion: spike up → short, spike down → long
            z = signal.metadata.get("zscore", 0)
            return Side.SHORT if z > 0 else Side.LONG

        if signal.signal_type == SignalType.VOLUME_SURGE:
            return Side.LONG   # momentum

        if signal.signal_type == SignalType.VWAP_DEVIATION:
            vwap  = signal.metadata.get("vwap", signal.price)
            # Price above VWAP → short (expect reversion down)
            return Side.SHORT if signal.price > vwap else Side.LONG

        if signal.signal_type == SignalType.VOLATILITY_BURST:
            return None  # too noisy for simple directional bet — skip

        return None

    def on_signal(self, signal: Signal):
        """Process an incoming signal and potentially open a trade."""
        if len(self.state.open_trades) >= self.cfg.max_positions:
            return

        # Don't double-up on same symbol
        open_syms = {t.symbol for t in self.state.open_trades}
        if signal.symbol in open_syms:
            return

        side = self._signal_to_side(signal)
        if side is None:
            return

        # Position sizing: fixed fraction of capital
        notional = self.cfg.initial_capital * self.cfg.position_size
        shares   = notional / signal.price
        cost     = notional * self.cfg.commission_pct

        if self.state.capital < notional + cost:
            logger.debug(f"Insufficient capital for {signal.symbol} trade")
            return

        self.state.capital -= cost
        trade = Trade(
            symbol      = signal.symbol,
            side        = side,
            entry_price = signal.price,
            entry_time  = signal.timestamp,
            shares      = shares,
            signal_type = signal.signal_type,
        )
        self.state.open_trades.append(trade)
        logger.debug(f"Opened {side} {signal.symbol} @ {signal.price:.2f} ({shares:.1f} shares)")

    def on_tick(self, tick: Tick):
        """Update open positions with current price, check exits."""
        self.state.last_prices[tick.symbol] = tick.price

        to_close = []
        for trade in self.state.open_trades:
            if trade.symbol != tick.symbol:
                continue

            trade.bars_held += 1
            upnl = trade.unrealized_pnl(tick.price)
            pct  = upnl / (trade.entry_price * trade.shares)

            reason = None
            if trade.bars_held >= self.cfg.hold_bars:
                reason = "TIME"
            elif pct <= -self.cfg.stop_loss_pct:
                reason = "STOP"
            elif pct >= self.cfg.take_profit_pct:
                reason = "TARGET"

            if reason:
                to_close.append((trade, tick.price, tick.timestamp, reason))

        for trade, price, ts, reason in to_close:
            self._close_trade(trade, price, ts, reason)

        # Snapshot equity
        total_upnl = sum(
            t.unrealized_pnl(self.state.last_prices.get(t.symbol, t.entry_price))
            for t in self.state.open_trades
        )
        self.state.equity_curve.append({
            "ts":     tick.timestamp.isoformat(),
            "equity": round(self.state.capital + total_upnl, 2),
            "open_positions": len(self.state.open_trades),
        })

    def _close_trade(self, trade: Trade, price: float, ts: datetime, reason: str):
        trade.exit_price  = price
        trade.exit_time   = ts
        trade.exit_reason = reason
        trade.pnl         = trade.unrealized_pnl(price)

        # Return notional + PnL to capital, minus commission
        notional  = trade.entry_price * trade.shares
        commission= notional * self.cfg.commission_pct
        self.state.capital += notional + trade.pnl - commission
        self.state.open_trades.remove(trade)
        self.state.closed_trades.append(trade)
        logger.debug(f"Closed {trade.side} {trade.symbol} @ {price:.2f} | PnL: {trade.pnl:+.2f} ({reason})")

    # ── Reporting ─────────────────────────────────────────────────────────

    def report(self) -> dict:
        """Return a full performance report dict."""
        trades = self.state.closed_trades
        if not trades:
            return {"error": "No closed trades yet."}

        pnls      = [t.pnl for t in trades]
        winners   = [p for p in pnls if p > 0]
        losers    = [p for p in pnls if p <= 0]
        total_pnl = sum(pnls)
        hit_rate  = len(winners) / len(pnls) * 100

        avg_win   = sum(winners) / len(winners) if winners else 0
        avg_loss  = sum(losers)  / len(losers)  if losers  else 0
        profit_factor = abs(sum(winners) / sum(losers)) if sum(losers) != 0 else float('inf')

        # Sharpe (annualised, assume 252 × 390 1-min bars/yr)
        import statistics
        if len(pnls) > 1:
            mean_r  = statistics.mean(pnls)
            std_r   = statistics.stdev(pnls)
            sharpe  = (mean_r / std_r) * (252 * 390) ** 0.5 if std_r > 0 else 0
        else:
            sharpe = 0

        # Max drawdown on equity curve
        equity  = [e["equity"] for e in self.state.equity_curve]
        peak    = self.cfg.initial_capital
        max_dd  = 0.0
        for e in equity:
            peak   = max(peak, e)
            max_dd = min(max_dd, (e - peak) / peak * 100)

        return {
            "summary": {
                "initial_capital": self.cfg.initial_capital,
                "final_capital":   round(self.state.capital, 2),
                "total_pnl":       round(total_pnl, 2),
                "total_return_pct":round(total_pnl / self.cfg.initial_capital * 100, 3),
                "open_positions":  len(self.state.open_trades),
            },
            "trade_stats": {
                "total_trades":    len(trades),
                "winners":         len(winners),
                "losers":          len(losers),
                "hit_rate_pct":    round(hit_rate, 1),
                "avg_win":         round(avg_win, 2),
                "avg_loss":        round(avg_loss, 2),
                "profit_factor":   round(profit_factor, 3),
                "largest_win":     round(max(pnls), 2),
                "largest_loss":    round(min(pnls), 2),
            },
            "risk_metrics": {
                "sharpe_ratio":    round(sharpe, 3),
                "max_drawdown_pct":round(max_dd, 3),
            },
            "exit_reasons": {
                r: sum(1 for t in trades if t.exit_reason == r)
                for r in ["TIME", "STOP", "TARGET"]
            },
            "by_signal_type": {
                st: {
                    "count": sum(1 for t in trades if t.signal_type == st),
                    "pnl":   round(sum(t.pnl for t in trades if t.signal_type == st), 2),
                }
                for st in set(t.signal_type for t in trades)
            },
            "equity_curve": self.state.equity_curve[-200:],  # last 200 points
        }

    def print_report(self):
        r = self.report()
        if "error" in r:
            print(r["error"]); return
        s = r["summary"]; t = r["trade_stats"]; k = r["risk_metrics"]
        print(f"""
╔══════════════════════════════════════════╗
║         P&L Simulator Report             ║
╚══════════════════════════════════════════╝

  Capital:   ${s['initial_capital']:>10,.0f}  →  ${s['final_capital']:>10,.2f}
  Total P&L: ${s['total_pnl']:>+10,.2f}  ({s['total_return_pct']:+.2f}%)

  Trades:    {t['total_trades']}  ({t['winners']} wins / {t['losers']} losses)
  Hit Rate:  {t['hit_rate_pct']}%
  Avg Win:   ${t['avg_win']:+,.2f}  |  Avg Loss: ${t['avg_loss']:+,.2f}
  P. Factor: {t['profit_factor']}

  Sharpe:    {k['sharpe_ratio']}
  Max DD:    {k['max_drawdown_pct']}%

  Exit reasons: {r['exit_reasons']}
""")
