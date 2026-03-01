"""
dashboard/app.py — Flask web dashboard with SSE streaming.

On startup, kicks off the market data pipeline in a background thread
so signals are detected and the DB is populated automatically —
no need to run main.py separately.
"""

import json
import os
import time
import random
import threading
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, render_template, jsonify, request

app = Flask(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "ticks.db"

# ── In-memory signal buffer ───────────────────────────────────────────────────
_signal_buffer: list[dict] = []
_signal_lock   = threading.Lock()

def push_signal(sig: dict):
    with _signal_lock:
        _signal_buffer.append(sig)
        if len(_signal_buffer) > 50:
            _signal_buffer.pop(0)

# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_conn():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(str(DB_PATH))

def get_symbols() -> list[str]:
    conn = _get_conn()
    if not conn:
        return ["AAPL", "MSFT", "SPY", "NVDA", "TSLA"]
    try:
        cur  = conn.execute("SELECT DISTINCT symbol FROM ticks ORDER BY symbol")
        syms = [r[0] for r in cur.fetchall()]
        return syms or ["AAPL", "MSFT", "SPY", "NVDA", "TSLA"]
    finally:
        conn.close()

def get_ticks(symbol: str, limit: int = 60) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur  = conn.execute("""
            SELECT ts, price, volume, high, low, vwap FROM ticks
            WHERE symbol = ? ORDER BY ts DESC LIMIT ?
        """, (symbol, limit))
        rows = cur.fetchall()
        return [{"ts": r[0], "price": r[1], "volume": r[2],
                 "high": r[3], "low": r[4], "vwap": r[5]}
                for r in reversed(rows)]
    finally:
        conn.close()

def get_latest_tick(symbol: str) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.execute("""
            SELECT ts, price, volume, high, low, vwap FROM ticks
            WHERE symbol = ? ORDER BY ts DESC LIMIT 1
        """, (symbol,))
        r = cur.fetchone()
        if not r:
            return None
        return {"ts": r[0], "price": r[1], "volume": r[2],
                "high": r[3], "low": r[4], "vwap": r[5]}
    finally:
        conn.close()

# ── Demo data (shown before first real tick arrives) ──────────────────────────

_BASES = {"AAPL": 182.5, "MSFT": 415.0, "SPY": 512.0, "NVDA": 875.0, "TSLA": 175.0}
_demo_state: dict[str, float] = {}

def demo_ticks(symbol: str, n: int = 60) -> list[dict]:
    base  = _BASES.get(symbol, 150.0)
    p     = base
    now   = datetime.utcnow()
    ticks = []
    for i in range(n):
        p    += random.gauss(0, base * 0.002)
        vol   = int(random.lognormvariate(11, 0.8))
        high  = p + abs(random.gauss(0, 0.3))
        low   = p - abs(random.gauss(0, 0.3))
        vwap  = p + random.gauss(0, 0.15)
        ts    = (now - timedelta(minutes=n - i)).isoformat()
        ticks.append({"ts": ts, "price": round(p, 2), "volume": vol,
                      "high": round(high, 2), "low": round(low, 2), "vwap": round(vwap, 2)})
    return ticks

def demo_next_tick(symbol: str) -> dict:
    base = _BASES.get(symbol, 150.0)
    p    = _demo_state.get(symbol, base)
    p   += random.gauss(0, base * 0.001)
    _demo_state[symbol] = p
    vol  = int(random.lognormvariate(11, 0.8))
    return {
        "ts":     datetime.utcnow().isoformat(),
        "price":  round(p, 2),
        "volume": vol,
        "high":   round(p + abs(random.gauss(0, 0.2)), 2),
        "low":    round(p - abs(random.gauss(0, 0.2)), 2),
        "vwap":   round(p + random.gauss(0, 0.1), 2),
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/symbols")
def api_symbols():
    return jsonify(get_symbols())

@app.route("/api/ticks/<symbol>")
def api_ticks(symbol):
    limit = int(request.args.get("limit", 60))
    rows  = get_ticks(symbol.upper(), limit)
    return jsonify(rows or demo_ticks(symbol.upper(), limit))

@app.route("/api/signals")
def api_signals():
    with _signal_lock:
        return jsonify(list(_signal_buffer))

@app.route("/stream/<symbol>")
def stream(symbol):
    sym = symbol.upper()
    def generate():
        while True:
            tick = get_latest_tick(sym) or demo_next_tick(sym)
            yield f"data: {json.dumps(tick)}\n\n"
            time.sleep(5)
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Background pipeline ───────────────────────────────────────────────────────

def _start_pipeline():
    """
    Run the polling pipeline in a background daemon thread.
    Fires automatically on server startup — no need to run main.py separately.
    Signals are written to the in-memory buffer and appear in /api/signals.
    """
    import logging
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.storage import DataStore
    from src.fetcher import MarketFetcher
    from src.signals import SignalDetector
    from src.alerts  import AlertManager, BaseChannel
    from src.signals import Signal

    # Custom alert channel that pushes into the dashboard's signal buffer
    class DashboardChannel(BaseChannel):
        def send(self, signal: Signal):
            push_signal({
                "ts":      signal.timestamp.isoformat(),
                "type":    signal.signal_type,
                "symbol":  signal.symbol,
                "price":   signal.price,
                "message": signal.message,
            })

    store    = DataStore(); store.initialize()
    fetcher  = MarketFetcher()
    detector = SignalDetector()
    alerts   = AlertManager(channels=[DashboardChannel()])
    symbols  = ["AAPL", "MSFT", "SPY", "NVDA", "TSLA"]

    logging.info("Background pipeline started.")
    while True:
        for sym in symbols:
            try:
                tick = fetcher.fetch(sym)
                if tick is None:
                    continue
                store.insert_tick(tick)
                history = store.get_recent(sym, 50)
                for sig in detector.detect(tick, history):
                    alerts.fire(sig)
            except Exception as e:
                logging.error(f"Pipeline error ({sym}): {e}")
        time.sleep(60)


_pipeline_thread = threading.Thread(target=_start_pipeline, daemon=True)
_pipeline_thread.start()

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
