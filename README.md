# 📈 Market Data Pipeline

A real-time market data pipeline with anomaly detection, a live web dashboard, and a signal backtester — built for extensibility and production-readiness.

---

## 🚀 Try It Live

| Method | Effort | What you get |
|--------|--------|--------------|
| [![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Demo-222?logo=github&logoColor=white)](https://farihatamboli.github.io/market-pipeline/) | Zero setup | Static demo with simulated live data |
| [![Launch Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/farihatamboli/market-pipeline/HEAD?urlpath=proxy/5050/) | ~2 min cold start | Real Flask app, real yfinance data, in-browser |
| [![Live App](market-pipeline-production.up.railway.app) | Always on | Full deployment, real data, shareable URL |

> **Quickest:** Click GitHub Pages — no wait, no account needed.

---

## Features

- **Live data ingestion** via `yfinance` (free) or **Alpaca WebSocket** (real-time)
- **SQLite persistence** — queryable tick store, easy to swap for TimescaleDB/Postgres
- **4 signal detectors**: price spike, volume surge, volatility burst, VWAP deviation
- **Web dashboard**: live price + VWAP chart, volume bars, signal feed, multi-symbol switcher
- **Signal backtester**: Jupyter notebook with forward return analysis, hit rates, and Sharpe ratios
- **Docker**: one command to run everything
- **Full test suite** with `pytest`

---

## Quickstart

### Local (no Docker)

```bash
git clone https://github.com/farihatamboli/market-pipeline.git
cd market-pipeline
pip install -r requirements.txt

# Terminal 1 — pipeline (yfinance polling)
python main.py --symbols AAPL MSFT SPY NVDA TSLA --interval 60

# Terminal 2 — dashboard
python -m dashboard.app
# → http://localhost:5050
```

### Docker (one command)

```bash
docker compose up
# → Dashboard at http://localhost:5050
# → Pipeline runs automatically alongside it
```

### Alpaca real-time stream

```bash
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret

python main.py --symbols AAPL MSFT SPY --stream alpaca
```

Sign up free at [alpaca.markets](https://alpaca.markets) — no card required for paper trading.

### Backtester

```bash
cd notebooks
jupyter notebook backtest.ipynb
```

---

## Architecture

```
main.py                    CLI — yfinance polling or Alpaca stream
docker-compose.yml         One-command deployment
Dockerfile
├── src/
│   ├── fetcher.py         yfinance ingestion → Tick dataclass
│   ├── alpaca_stream.py   Real-time WebSocket stream (Alpaca)
│   ├── storage.py         SQLite persistence layer
│   ├── signals.py         Stateless anomaly detectors
│   ├── alerts.py          Console + file + Slack alert channels
│   └── pipeline.py        Polling orchestration loop
├── dashboard/
│   ├── app.py             Flask + SSE streaming server
│   └── templates/
│       └── dashboard.html Live web UI (Chart.js)
├── notebooks/
│   └── backtest.ipynb     Signal quality analysis
├── tests/
│   └── test_signals.py    pytest unit tests
└── binder/                Binder config (live demo)
```

---

## Signals

| Signal | Trigger | Configurable |
|--------|---------|-------------|
| `PRICE_SPIKE` | Price > 2.5σ from rolling mean | `price_spike_zscore` |
| `VOLUME_SURGE` | Volume > 3× rolling average | `volume_surge_multiplier` |
| `VOLATILITY_BURST` | H-L range > 2.5× rolling average | `volatility_burst_multiplier` |
| `VWAP_DEVIATION` | Price > 0.5% from session VWAP | `vwap_deviation_pct` |

```python
detector = SignalDetector(
    price_spike_zscore          = 3.0,   # tighten/loosen sensitivity
    volume_surge_multiplier     = 4.0,
    volatility_burst_multiplier = 2.0,
    vwap_deviation_pct          = 1.0,
)
```

---

## Live Demo Setup

### Option 1 — GitHub Pages (zero effort)

1. Repo → **Settings → Pages → Source: main branch / root**
2. Copy `dashboard/templates/dashboard.html` → repo root as `index.html`
3. Update badge URL: `https://farihatamboli.github.io/market-pipeline/`

### Option 2 — Binder (~2 min cold start)

The `binder/` folder is already configured. Just update the badge URL with your username:
```
https://mybinder.org/v2/gh/farihatamboli/market-pipeline/HEAD?urlpath=proxy/5050/
```

### Option 3 — Railway (always-on, no card required)

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
2. Select this repo
3. **Variables** tab → add `PORT = 5050`
4. **Settings → Deploy → Start Command:**
   ```
   python -m dashboard.app
   ```
5. **Settings → Networking → Generate Domain** → copy URL into badge

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Extending

**New signal** — add a `_check_*` method in `src/signals.py`, call it from `detect()`.

**Slack alerts** — set `SLACK_WEBHOOK_URL` env var and uncomment the Slack channel in `src/alerts.py`.

**TimescaleDB** — implement the `insert_tick` / `get_recent` / `get_range` interface in a new `TimescaleStore` class and swap it in.

**More symbols** — just pass them via `--symbols`. No other changes needed.

---

## Tech Stack

- Python 3.11+
- `yfinance` + `websocket-client` (Alpaca) for market data
- `flask` + Server-Sent Events for live dashboard
- `sqlite3` (stdlib) for storage
- `Chart.js` for charting
- `pandas` + `matplotlib` for backtesting
- `pytest` for testing
- `Docker` + `docker-compose` for deployment

---

## Design Notes

**SSE over WebSockets** — the dashboard uses Server-Sent Events deliberately. SSE is plain HTTP, auto-reconnects on failure, works through proxies and load balancers, and is the right fit for one-directional server → browser streaming. No extra library needed.

**Stateless `SignalDetector`** — pure function signature `(tick, history) → signals`. No hidden state, trivially parallelisable across symbols, and unit-testable without mocking.

**Swappable data sources** — `MarketFetcher` (yfinance) and `AlpacaStream` both produce the same `Tick` dataclass, so the storage and signal layers are completely agnostic to the data source.
