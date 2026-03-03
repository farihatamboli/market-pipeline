"""
src/api.py — REST API with OpenAPI documentation.

Exposes the market data pipeline as a documented HTTP API.
Auto-generates OpenAPI 3.0 spec — browse at /api/docs

Endpoints:
  GET  /api/v1/ticks/{symbol}          Latest N ticks
  GET  /api/v1/ticks/{symbol}/range    Ticks in time range
  GET  /api/v1/signals                 Recent signals (all symbols)
  GET  /api/v1/signals/{symbol}        Signals for one symbol
  GET  /api/v1/symbols                 Available symbols
  GET  /api/v1/status                  Pipeline health check
  POST /api/v1/simulate                Run P&L simulation on stored data
  GET  /api/docs                       OpenAPI UI (Swagger)
  GET  /api/openapi.json               Raw OpenAPI spec
"""

import json
import time
import logging
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, render_template_string, current_app

logger = logging.getLogger(__name__)

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# ── Request timing middleware ─────────────────────────────────────────────────

_request_times: list[float] = []

def timed(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = f(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        _request_times.append(elapsed)
        if len(_request_times) > 1000:
            _request_times.pop(0)
        if hasattr(result, "headers"):
            result.headers["X-Response-Time-Ms"] = f"{elapsed:.2f}"
        return result
    return wrapper

# ── Helpers ───────────────────────────────────────────────────────────────────

def _store():
    """Get storage backend from app context."""
    return current_app.config.get("STORE")

def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code

def _tick_to_dict(tick) -> dict:
    return {
        "symbol":    tick.symbol,
        "timestamp": tick.timestamp.isoformat(),
        "price":     tick.price,
        "volume":    tick.volume,
        "open":      tick.open,
        "high":      tick.high,
        "low":       tick.low,
        "vwap":      tick.vwap,
    }

# ── Endpoints ─────────────────────────────────────────────────────────────────

@api_bp.route("/symbols")
@timed
def get_symbols():
    """
    ---
    summary: List available symbols
    description: Returns all symbols that have data in the store.
    responses:
      200:
        description: List of ticker symbols
    """
    store = _store()
    if not store:
        return _err("Store not initialized", 503)
    return jsonify({"symbols": store.get_symbols()})


@api_bp.route("/ticks/<symbol>")
@timed
def get_ticks(symbol: str):
    """
    ---
    summary: Get recent ticks for a symbol
    parameters:
      - name: symbol
        in: path
        required: true
        schema: {type: string}
      - name: limit
        in: query
        schema: {type: integer, default: 60, maximum: 500}
    responses:
      200:
        description: Array of tick objects
    """
    store = _store()
    if not store:
        return _err("Store not initialized", 503)

    limit = min(int(request.args.get("limit", 60)), 500)
    ticks = store.get_recent(symbol.upper(), limit)
    return jsonify({
        "symbol": symbol.upper(),
        "count":  len(ticks),
        "ticks":  [_tick_to_dict(t) for t in ticks],
    })


@api_bp.route("/ticks/<symbol>/range")
@timed
def get_ticks_range(symbol: str):
    """
    ---
    summary: Get ticks within a time range
    parameters:
      - name: symbol
        in: path
        required: true
      - name: start
        in: query
        required: true
        schema: {type: string, example: "2024-01-15T09:30:00"}
      - name: end
        in: query
        required: true
        schema: {type: string, example: "2024-01-15T16:00:00"}
    responses:
      200:
        description: Array of tick objects in range
    """
    store = _store()
    if not store:
        return _err("Store not initialized", 503)

    start = request.args.get("start")
    end   = request.args.get("end")
    if not start or not end:
        return _err("start and end query params required")

    ticks = store.get_range(symbol.upper(), start, end)
    return jsonify({
        "symbol": symbol.upper(),
        "start":  start,
        "end":    end,
        "count":  len(ticks),
        "ticks":  [_tick_to_dict(t) for t in ticks],
    })


@api_bp.route("/signals")
@timed
def get_signals():
    """
    ---
    summary: Get recent signals across all symbols
    parameters:
      - name: limit
        in: query
        schema: {type: integer, default: 50, maximum: 200}
      - name: type
        in: query
        schema:
          type: string
          enum: [PRICE_SPIKE, VOLUME_SURGE, VOLATILITY_BURST, VWAP_DEVIATION]
    responses:
      200:
        description: Array of signal objects
    """
    buffer = current_app.config.get("SIGNAL_BUFFER", [])
    sig_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 50)), 200)

    sigs = buffer
    if sig_type:
        sigs = [s for s in sigs if s.get("type") == sig_type]

    return jsonify({
        "count":   len(sigs[-limit:]),
        "signals": sigs[-limit:],
    })


@api_bp.route("/signals/<symbol>")
@timed
def get_signals_for_symbol(symbol: str):
    """
    ---
    summary: Get signals for a specific symbol
    """
    buffer = current_app.config.get("SIGNAL_BUFFER", [])
    sigs = [s for s in buffer if s.get("symbol") == symbol.upper()]
    return jsonify({"symbol": symbol.upper(), "count": len(sigs), "signals": sigs})


@api_bp.route("/status")
@timed
def get_status():
    """
    ---
    summary: Pipeline health check
    description: Returns pipeline status, uptime, data source info, and latency stats.
    responses:
      200:
        description: Health status object
    """
    store   = _store()
    symbols = store.get_symbols() if store else []
    avg_lat = (sum(_request_times) / len(_request_times)) if _request_times else 0
    p99_lat = sorted(_request_times)[int(len(_request_times) * 0.99)] if len(_request_times) > 100 else 0

    return jsonify({
        "status":   "ok",
        "store":    "timescaledb" if "TimescaleStore" in str(type(store)) else "sqlite",
        "symbols":  symbols,
        "latency":  {
            "avg_ms":   round(avg_lat, 2),
            "p99_ms":   round(p99_lat, 2),
            "samples":  len(_request_times),
        },
        "pipeline": {
            "running": current_app.config.get("PIPELINE_RUNNING", False),
        },
        "timestamp": datetime.utcnow().isoformat(),
    })


@api_bp.route("/simulate", methods=["POST"])
@timed
def simulate():
    """
    ---
    summary: Run P&L simulation on stored data
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              symbol:          {type: string, example: AAPL}
              initial_capital: {type: number, default: 100000}
              position_size:   {type: number, default: 0.05}
              hold_bars:       {type: integer, default: 15}
              stop_loss_pct:   {type: number, default: 0.005}
    responses:
      200:
        description: P&L simulation report
    """
    from .pnl_simulator import PnLSimulator, SimConfig
    from .signals import SignalDetector

    body   = request.get_json(force=True) or {}
    symbol = body.get("symbol", "AAPL").upper()
    store  = _store()

    if not store:
        return _err("Store not initialized", 503)

    ticks = store.get_recent(symbol, 200)
    if len(ticks) < 20:
        return _err(f"Insufficient data for {symbol} (need ≥20 ticks, have {len(ticks)})")

    cfg = SimConfig(
        initial_capital = float(body.get("initial_capital", 100_000)),
        position_size   = float(body.get("position_size", 0.05)),
        hold_bars       = int(body.get("hold_bars", 15)),
        stop_loss_pct   = float(body.get("stop_loss_pct", 0.005)),
    )

    sim      = PnLSimulator(cfg)
    detector = SignalDetector()
    history  = []

    for tick in ticks:
        history.append(tick)
        signals = detector.detect(tick, history[-50:])
        for sig in signals:
            sim.on_signal(sig)
        sim.on_tick(tick)

    return jsonify(sim.report())


# ── OpenAPI spec ──────────────────────────────────────────────────────────────

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title":       "Market Data Pipeline API",
        "version":     "1.0.0",
        "description": "Real-time market data, anomaly signals, and P&L simulation.",
        "contact":     {"name": "GitHub", "url": "https://github.com/YOUR_USERNAME/market-pipeline"},
    },
    "servers": [{"url": "/api/v1", "description": "Production"}],
    "paths": {
        "/symbols":           {"get": {"summary": "List symbols",          "tags": ["Data"]}},
        "/ticks/{symbol}":    {"get": {"summary": "Recent ticks",          "tags": ["Data"],    "parameters": [{"name":"symbol","in":"path","required":True,"schema":{"type":"string"}},{"name":"limit","in":"query","schema":{"type":"integer","default":60}}]}},
        "/ticks/{symbol}/range": {"get": {"summary": "Ticks in time range","tags": ["Data"]}},
        "/signals":           {"get": {"summary": "All recent signals",    "tags": ["Signals"]}},
        "/signals/{symbol}":  {"get": {"summary": "Signals for symbol",   "tags": ["Signals"]}},
        "/status":            {"get": {"summary": "Health & latency",      "tags": ["System"]}},
        "/simulate":          {"post":{"summary": "Run P&L simulation",    "tags": ["Research"]}},
    },
    "tags": [
        {"name": "Data",     "description": "Market tick data"},
        {"name": "Signals",  "description": "Anomaly detection signals"},
        {"name": "System",   "description": "Health & diagnostics"},
        {"name": "Research", "description": "Backtesting & simulation"},
    ],
}

SWAGGER_UI = """<!DOCTYPE html>
<html><head>
<title>MDP API Docs</title>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.10.3/swagger-ui.min.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.10.3/swagger-ui-bundle.min.js"></script>
<script>
window.onload = () => SwaggerUIBundle({
  url: "/api/openapi.json",
  dom_id: "#swagger-ui",
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  layout: "StandaloneLayout",
  theme: "dark",
});
</script></body></html>"""


def register_api(app, store=None, signal_buffer=None):
    """
    Register the API blueprint with the Flask app.

    Call from dashboard/app.py:
        from src.api import register_api
        register_api(app, store=store, signal_buffer=_signal_buffer)
    """
    app.config["STORE"]         = store
    app.config["SIGNAL_BUFFER"] = signal_buffer or []

    app.register_blueprint(api_bp)

    @app.route("/api/openapi.json")
    def openapi_json():
        return jsonify(OPENAPI_SPEC)

    @app.route("/api/docs")
    def api_docs():
        return render_template_string(SWAGGER_UI)

    logger.info("REST API registered — docs at /api/docs")
