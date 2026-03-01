"""
src/alpaca_stream.py — Real-time tick stream via Alpaca WebSocket API.

Alpaca's free paper-trading account gives you real-time IEX data.
Sign up at alpaca.markets — no card required.

Usage:
    export ALPACA_API_KEY=your_key
    export ALPACA_SECRET_KEY=your_secret

    from src.alpaca_stream import AlpacaStream
    from src.storage import DataStore
    from src.signals import SignalDetector
    from src.alerts import AlertManager

    store    = DataStore(); store.initialize()
    detector = SignalDetector()
    alerts   = AlertManager()

    def on_tick(tick):
        store.insert_tick(tick)
        history = store.get_recent(tick.symbol, 50)
        for sig in detector.detect(tick, history):
            alerts.fire(sig)

    stream = AlpacaStream(symbols=["AAPL", "MSFT", "SPY"], on_tick=on_tick)
    stream.run()  # blocks — run in its own thread or process
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from .fetcher import Tick

logger = logging.getLogger(__name__)

try:
    import websocket  # pip install websocket-client
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False


ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"


class AlpacaStream:
    """
    Streams real-time trade data from Alpaca via WebSocket.

    Requires:
        pip install websocket-client
        ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.

    Args:
        symbols:  List of tickers to subscribe to, e.g. ['AAPL', 'MSFT']
        on_tick:  Callback invoked with each Tick as it arrives
    """

    def __init__(self, symbols: list[str], on_tick: Callable[[Tick], None]):
        if not _WS_AVAILABLE:
            raise ImportError("pip install websocket-client")

        self.symbols  = [s.upper() for s in symbols]
        self.on_tick  = on_tick
        self.api_key  = os.environ.get("ALPACA_API_KEY", "")
        self.secret   = os.environ.get("ALPACA_SECRET_KEY", "")
        self._ws      = None
        self._running = False

        if not self.api_key or not self.secret:
            raise EnvironmentError(
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.\n"
                "Sign up free at https://alpaca.markets (no card required)."
            )

    # ── WebSocket callbacks ───────────────────────────────────────────────────

    def _on_open(self, ws):
        logger.info("Alpaca WS connected — authenticating...")
        ws.send(json.dumps({
            "action": "auth",
            "key":    self.api_key,
            "secret": self.secret,
        }))

    def _on_message(self, ws, message):
        events = json.loads(message)
        for event in events:
            msg_type = event.get("T")

            if msg_type == "success" and event.get("msg") == "authenticated":
                logger.info("Alpaca authenticated — subscribing to trades...")
                ws.send(json.dumps({
                    "action": "subscribe",
                    "trades": self.symbols,
                }))

            elif msg_type == "t":  # trade event
                try:
                    tick = self._parse_trade(event)
                    self.on_tick(tick)
                except Exception as e:
                    logger.error(f"Error parsing trade: {e} | raw={event}")

            elif msg_type == "error":
                logger.error(f"Alpaca error: {event}")

    def _on_error(self, ws, error):
        logger.error(f"Alpaca WS error: {error}")

    def _on_close(self, ws, code, msg):
        logger.info(f"Alpaca WS closed ({code}): {msg}")
        if self._running:
            logger.info("Reconnecting in 5s...")
            threading.Timer(5.0, self.run).start()

    # ── Trade parser ──────────────────────────────────────────────────────────

    def _parse_trade(self, event: dict) -> Tick:
        """
        Convert a raw Alpaca trade event into a Tick.

        Alpaca trade format:
          { "T": "t", "S": "AAPL", "p": 182.50, "s": 100,
            "t": "2024-01-15T14:30:00.123Z", ... }
        """
        ts_raw = event.get("t", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            ts = ts.replace(tzinfo=None)  # store as naive UTC
        except Exception:
            ts = datetime.utcnow()

        price = float(event.get("p", 0))
        size  = int(event.get("s", 0))

        return Tick(
            symbol    = event.get("S", ""),
            timestamp = ts,
            price     = price,
            volume    = size,
            open      = price,   # trades don't carry OHLC — use price as proxy
            high      = price,
            low       = price,
            vwap      = None,    # compute externally from trade history
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        """Start the WebSocket stream (blocking)."""
        self._running = True
        self._ws = websocket.WebSocketApp(
            ALPACA_WS_URL,
            on_open    = self._on_open,
            on_message = self._on_message,
            on_error   = self._on_error,
            on_close   = self._on_close,
        )
        logger.info(f"Connecting to Alpaca stream | symbols={self.symbols}")
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def stop(self):
        """Gracefully close the stream."""
        self._running = False
        if self._ws:
            self._ws.close()
        logger.info("Alpaca stream stopped.")
