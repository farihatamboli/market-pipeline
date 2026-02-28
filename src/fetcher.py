"""
fetcher.py — Fetches real-time (or near-real-time) market data.

Uses yfinance as the primary source (free, no API key needed).
Falls back gracefully if data is unavailable.

Note: yfinance 1-minute data has a ~15-min delay for free users.
For true real-time, swap in an Alpaca WebSocket (see alpaca_stream.py).
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
    """A single market data point for one symbol at one moment."""
    symbol: str
    timestamp: datetime
    price: float
    volume: int
    open: float
    high: float
    low: float
    vwap: float | None = None


class MarketFetcher:
    """Fetches the latest market tick for a given symbol via yfinance."""

    def fetch(self, symbol: str) -> Tick | None:
        """
        Pull the most recent 1-minute bar for `symbol`.

        Returns a Tick or None if unavailable.
        """
        if yf is None:
            raise ImportError("yfinance is required: pip install yfinance")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="1m")

            if df.empty:
                logger.warning(f"{symbol}: empty history — market may be closed.")
                return None

            latest = df.iloc[-1]
            ts = df.index[-1].to_pydatetime()

            # Compute a simple VWAP proxy: cumulative (price * vol) / cumulative vol
            vwap = None
            if df["Volume"].sum() > 0:
                vwap = (df["Close"] * df["Volume"]).sum() / df["Volume"].sum()

            return Tick(
                symbol=symbol,
                timestamp=ts,
                price=float(latest["Close"]),
                volume=int(latest["Volume"]),
                open=float(latest["Open"]),
                high=float(latest["High"]),
                low=float(latest["Low"]),
                vwap=round(float(vwap), 4) if vwap else None,
            )

        except Exception as e:
            logger.error(f"Fetch error for {symbol}: {e}")
            return None
