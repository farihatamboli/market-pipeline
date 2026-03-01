"""
src/fetcher.py — Fetches market data via yfinance (polling fallback).

For real-time streaming, see src/alpaca_stream.py.
yfinance 1-min bars have a ~15-min delay on the free tier — fine for
signal research, but swap in Alpaca for true live trading infra.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    yf = None

logger = logging.getLogger(__name__)


@dataclass
class Tick:
    """A single market data point."""
    symbol:    str
    timestamp: datetime
    price:     float
    volume:    int
    open:      float
    high:      float
    low:       float
    vwap:      float | None = None


class MarketFetcher:
    """Polls yfinance for the latest 1-minute bar."""

    def fetch(self, symbol: str) -> Tick | None:
        if yf is None:
            raise ImportError("pip install yfinance")
        try:
            df = yf.Ticker(symbol).history(period="1d", interval="1m")
            if df.empty:
                logger.warning(f"{symbol}: empty — market may be closed.")
                return None
            latest = df.iloc[-1]
            ts     = df.index[-1].to_pydatetime()
            vwap   = None
            if df["Volume"].sum() > 0:
                vwap = (df["Close"] * df["Volume"]).sum() / df["Volume"].sum()
            return Tick(
                symbol    = symbol,
                timestamp = ts,
                price     = float(latest["Close"]),
                volume    = int(latest["Volume"]),
                open      = float(latest["Open"]),
                high      = float(latest["High"]),
                low       = float(latest["Low"]),
                vwap      = round(float(vwap), 4) if vwap else None,
            )
        except Exception as e:
            logger.error(f"Fetch error {symbol}: {e}")
            return None
