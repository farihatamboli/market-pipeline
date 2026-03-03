"""
src/socketio_feed.py — Flask-SocketIO WebSocket feed.

Replaces polling with true server-push WebSocket events.
The browser connects once and receives updates the instant new data arrives.

Events emitted by server → client:
  tick      {symbol, ts, price, volume, vwap, ...}
  signal    {ts, type, symbol, price, message}
  status    {source, pipeline_running}

Events received from client → server:
  subscribe   {symbol: "AAPL"}    — start receiving ticks for symbol
  unsubscribe {symbol: "AAPL"}    — stop

Usage — add to dashboard/app.py:
    from src.socketio_feed import init_socketio, emit_tick, emit_signal
    socketio = init_socketio(app)
    socketio.run(app, host="0.0.0.0", port=port)

Install:
    pip install flask-socketio gevent-websocket
    # OR
    pip install flask-socketio eventlet
"""

import logging
import os

logger = logging.getLogger(__name__)

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    _SOCKETIO_AVAILABLE = True
except ImportError:
    _SOCKETIO_AVAILABLE = False
    logger.warning(
        "flask-socketio not installed. WebSocket feed disabled.\n"
        "Install with: pip install flask-socketio eventlet"
    )

# Global SocketIO instance — set by init_socketio()
_socketio = None


def init_socketio(app, cors_allowed_origins="*"):
    """
    Attach SocketIO to the Flask app and register event handlers.

    Args:
        app: Flask application
        cors_allowed_origins: CORS setting (use your domain in production)

    Returns:
        SocketIO instance (use socketio.run(app, ...) instead of app.run())
    """
    global _socketio

    if not _SOCKETIO_AVAILABLE:
        logger.warning("SocketIO unavailable — falling back to polling mode.")
        return None

    # async_mode options:
    #   "eventlet"  — best performance, pip install eventlet
    #   "gevent"    — alternative, pip install gevent gevent-websocket
    #   "threading" — development only, no production concurrency
    async_mode = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")

    _socketio = SocketIO(
        app,
        cors_allowed_origins=cors_allowed_origins,
        async_mode=async_mode,
        logger=False,
        engineio_logger=False,
    )

    @_socketio.on("connect")
    def on_connect():
        client_id = getattr(emit.__self__, "sid", "unknown") if hasattr(emit, "__self__") else "?"
        logger.info(f"WebSocket client connected")
        emit("status", {"connected": True, "mode": "websocket"})

    @_socketio.on("disconnect")
    def on_disconnect():
        logger.info("WebSocket client disconnected")

    @_socketio.on("subscribe")
    def on_subscribe(data):
        """Client subscribes to a symbol's room."""
        symbol = str(data.get("symbol", "")).upper()
        if symbol:
            join_room(symbol)
            emit("subscribed", {"symbol": symbol})
            logger.debug(f"Client subscribed to {symbol}")

    @_socketio.on("unsubscribe")
    def on_unsubscribe(data):
        symbol = str(data.get("symbol", "")).upper()
        if symbol:
            leave_room(symbol)
            emit("unsubscribed", {"symbol": symbol})

    logger.info(f"SocketIO initialized (async_mode={async_mode})")
    return _socketio


def emit_tick(tick_dict: dict):
    """
    Broadcast a tick to all clients subscribed to that symbol's room.
    Call this from the pipeline whenever a new tick arrives.

    Args:
        tick_dict: dict with keys: symbol, ts, price, volume, vwap, high, low
    """
    if not _socketio:
        return
    symbol = tick_dict.get("symbol", "")
    _socketio.emit("tick", tick_dict, room=symbol)


def emit_signal(signal_dict: dict):
    """
    Broadcast a signal to all connected clients (no room filter — signals go everywhere).
    """
    if not _socketio:
        return
    _socketio.emit("signal", signal_dict)


def emit_status(status_dict: dict):
    """Broadcast pipeline status update to all clients."""
    if not _socketio:
        return
    _socketio.emit("status", status_dict)


# ── Client-side JS snippet ────────────────────────────────────────────────────
# Include this in dashboard.html to switch from polling to WebSocket:

CLIENT_JS = """
// ── WebSocket via Socket.IO ─────────────────────────────────────────────────
// Replace setInterval(pollTicks, 5000) with this for true push updates

const socket = io();

socket.on('connect', () => {
  console.log('WebSocket connected');
  socket.emit('subscribe', { symbol: activeSymbol });
});

socket.on('tick', (tick) => {
  // Drop into existing cache + render pipeline
  if (!cache[tick.symbol]) cache[tick.symbol] = [];
  cache[tick.symbol].push(tick);
  if (cache[tick.symbol].length > 120) cache[tick.symbol].shift();
  if (tick.symbol === activeSymbol) renderSingle(cache[tick.symbol]);
  if (cache[tick.symbol].length) updateChip(tick.symbol, tick);
});

socket.on('signal', (sig) => {
  addSig(sig);
});

// Re-subscribe when switching symbols
function switchSymbolWS(sym) {
  socket.emit('unsubscribe', { symbol: activeSymbol });
  activeSymbol = sym;
  socket.emit('subscribe', { symbol: sym });
}

// NOTE: Keep setInterval(pollSignals, 5000) as fallback for signal history
// Remove setInterval(pollTicks, 5000) once WebSocket is confirmed working
"""
