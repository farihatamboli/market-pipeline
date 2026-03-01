# 📈 Market Data Pipeline

A real-time market data pipeline with anomaly detection and a live web dashboard — built for extensibility and production-readiness.

---

## 🚀 Try It Live

| Method | Effort | What you get |
|--------|--------|--------------|
| [![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Demo-222?logo=github&logoColor=white)](https://farihatamboli.github.io/market-pipeline/dashboard-preview.html) | Zero setup | Static demo with simulated live data |
| [![Launch Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/farihatamboli/market-pipeline/HEAD?urlpath=proxy/5050/) | ~2 min cold start | Real Flask app, real yfinance data, in-browser |
| [![Live App](https://img.shields.io/badge/Live%20App-Railway-0B0D0E?logo=railway&logoColor=white)](https://market-pipeline.up.railway.app) | Always on | Full deployment, real data, shareable URL |

> **Quickest option:** Click the GitHub Pages badge — no wait, no account needed.

---

## Features

- **Live data ingestion** via `yfinance` (free, no API key required)
- **SQLite persistence** — queryable tick store, easy to swap for TimescaleDB/Postgres
- **4 signal detectors**: price spike, volume surge, volatility burst, VWAP deviation
- **Web dashboard**: live price + VWAP chart, volume bars, signal feed, multi-symbol switcher
- **Multi-channel alerting**: console, file log, and a Slack stub
- **Clean module architecture**: fetcher → storage → signals → alerts
- **Full test suite** with `pytest`

---

## Quickstart (Local)

```bash
git clone https://github.com/farihatamboli/market-pipeline.git
cd market-pipeline
pip install -r requirements.txt

# Terminal 1 — run the pipeline
python main.py --symbols AAPL MSFT SPY NVDA TSLA --interval 60

# Terminal 2 — run the dashboard
python -m dashboard.app
# → Open http://localhost:5050
```

---

## Architecture

```
main.py              CLI entrypoint
dashboard/
  app.py             Flask server + SSE streaming
  templates/
    dashboard.html   Live web UI (Chart.js)
src/
  pipeline.py        Orchestration loop
  fetcher.py         yfinance ingestion → Tick dataclass
  storage.py         SQLite persistence layer
  signals.py         Stateless anomaly detectors
  alerts.py          Multi-channel alert dispatcher
tests/
  test_signals.py    pytest unit tests
```

---

## Signals

| Signal | Trigger |
|--------|---------|
| `PRICE_SPIKE` | Price > 2.5σ from rolling mean |
| `VOLUME_SURGE` | Volume > 3× rolling average |
| `VOLATILITY_BURST` | H-L range > 2.5× rolling average |
| `VWAP_DEVIATION` | Price > 0.5% from session VWAP |

All thresholds are configurable via `SignalDetector(...)`.

---

## Live Demo Setup Guide

### Option 1 — GitHub Pages (static demo, zero effort)

1. Go to your repo → **Settings → Pages**
2. Set source to `main` branch, `/ (root)` folder
3. Copy `dashboard/templates/dashboard-preview.html` to the repo root and rename it `index.html` — or place it at `docs/index.html` and set Pages source to `/docs`
4. Replace the badge URL above with:
   ```
   https://farihatamboli.github.io/market-pipeline/
   ```
The demo uses simulated data and works entirely in the browser — no server needed.

---

### Option 2 — Binder (real Flask app, no account needed for visitors)

Binder runs your repo in a free cloud container. Add these two files to your repo root:

**`binder/requirements.txt`** — same as your main `requirements.txt`:
```
flask>=3.0.0
yfinance>=0.2.36
pandas>=2.0.0
```

**`binder/postBuild`** (no extension):
```bash
#!/bin/bash
echo "Binder setup complete"
```

**`start`** (repo root, no extension, make it executable with `chmod +x start`):
```bash
#!/bin/bash
python -m dashboard.app
```

Then update the Binder badge URL — replace `farihatamboli`:
```
https://mybinder.org/v2/gh/farihatamboli/market-pipeline/HEAD?urlpath=proxy/5050/
```

> ⚠️ Cold start takes ~2 minutes the first time. Once warm, it's instant.

---

### Option 3 — Railway (always-on, real data, no card required)

Railway gives you $5/month free credit — enough to keep this app running continuously.

1. Push your repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
3. Select your `market-pipeline` repo
4. Click **Add variables** and set:
   - `PORT` = `5050`
5. Click **Settings → Networking → Generate Domain** to get your public URL
6. Railway auto-detects Python — set the start command under **Settings → Deploy**:
   ```
   python -m dashboard.app
   ```
7. Replace the badge URL above with your Railway domain, e.g.:
   ```
   https://market-pipeline.up.railway.app
   ```

> ⚠️ Free tier has a monthly usage cap (~500 hours). More than enough for a portfolio project.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Extending

**Add a new signal** — implement a `_check_*` method in `signals.py` and call it from `detect()`.

**Add Slack alerts** — set `SLACK_WEBHOOK_URL` env var and uncomment the Slack channel in `alerts.py`.

**Scale up** — replace `DataStore` with a `TimescaleDB` adapter and `MarketFetcher` with an Alpaca WebSocket stream.

---

## Tech Stack

- Python 3.11+
- `yfinance` for market data
- `flask` + Server-Sent Events for the live dashboard
- `sqlite3` (stdlib) for storage
- `Chart.js` for charting
- `pytest` for testing

---

## Design Notes

The dashboard uses **Server-Sent Events** over WebSockets — a deliberate choice. SSE is simpler (plain HTTP), auto-reconnects on failure, works through proxies and load balancers, and is the right fit for one-directional server → browser data streaming. The `SignalDetector` is stateless by design (pure function: tick + history → signals), making it trivially unit-testable and easy to parallelize.
