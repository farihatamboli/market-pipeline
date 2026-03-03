# 📈 Market Data Pipeline

A production-grade real-time market data pipeline with anomaly detection, live dashboards, backtesting, and full deployment infrastructure.

---

## 🚀 Try It Live

| | Method | What you get |
|---|--------|--------------|
| [![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/YOUR_USERNAME/market-pipeline/HEAD?urlpath=proxy/5050/) | ~2 min | Real Flask app, real yfinance data |
| [![Live App](https://img.shields.io/badge/Live-Railway-0B0D0E?logo=railway)](https://YOUR_RAILWAY_DOMAIN.up.railway.app) | Always on | Full deployment, real data |

[![CI](https://github.com/YOUR_USERNAME/market-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/market-pipeline/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)

---

## Features

### Data Pipeline
- **yfinance polling** — 1-min OHLCV bars, free, no API key needed
- **Alpaca WebSocket** — true real-time tick stream (`--stream alpaca`)
- **SQLite** for local dev; **TimescaleDB** adapter for production (hypertables, continuous aggregates, `time_bucket` queries)
- **One-shot SQLite → TimescaleDB migration** utility included

### Signal Detection
| Signal | Trigger |
|--------|---------|
| `PRICE_SPIKE` | Price > 2.5σ from rolling mean |
| `VOLUME_SURGE` | Volume > 3× rolling average |
| `VOLATILITY_BURST` | H-L range > 2.5× rolling average |
| `VWAP_DEVIATION` | Price > 0.5% from session VWAP |

### Alerts
- Console + file channels (always on)
- **Discord webhook** — rich embeds, color-coded by signal type
- **Slack webhook** — Block Kit formatting
- Per-symbol rate limiting to prevent alert floods

### Web Dashboard (`dashboard/`)
- Live price + VWAP chart with MA20, MA50, Bollinger Bands, RSI
- Candlestick mode
- **Side-by-side compare** — up to 4 symbols
- **Overlay % compare** — normalised returns on one chart
- **S&P 500 search** — 500+ tickers with company name search
- Watchlist bar with live price/% change per symbol

### Research Dashboard (`streamlit_app/`)
- Interactive OHLCV explorer with Plotly
- Signal quality analysis with forward returns and hit rates
- P&L simulator with equity curve
- Correlation heatmap across symbols

### REST API (`/api/v1/`)
- `GET /api/v1/ticks/{symbol}` — latest N ticks
- `GET /api/v1/signals` — recent signals
- `GET /api/v1/status` — health + latency stats
- `POST /api/v1/simulate` — run P&L simulation
- Swagger UI at `/api/docs`

### Performance Benchmarks (`benchmarks/`)
- Signal detection latency (mean, P95, P99)
- Per-detector micro-benchmarks (µs resolution)
- SQLite read/write throughput
- End-to-end tick processing latency
- Memory profiling with `tracemalloc`

### CI/CD (`.github/workflows/ci.yml`)
- Tests on Python 3.11 + 3.12
- Coverage reporting to Codecov
- Ruff lint + format checks
- Benchmarks run on every merge to main
- Docker build validation

### P&L Simulator (`src/pnl_simulator.py`)
- Mean-reversion strategy on price spikes
- Momentum on volume surges
- Configurable position sizing, hold period, stop-loss, take-profit
- Sharpe ratio, max drawdown, profit factor reporting

---

## Quickstart

### Local
```bash
git clone https://github.com/YOUR_USERNAME/market-pipeline.git
cd market-pipeline
pip install -r requirements.txt

# Terminal 1 — pipeline
python main.py --symbols AAPL MSFT SPY NVDA TSLA --interval 60

# Terminal 2 — web dashboard
python -m dashboard.app
# → http://localhost:5050

# Terminal 3 — research dashboard
streamlit run streamlit_app/app.py
# → http://localhost:8501
```

### Docker
```bash
docker compose up
```

### With webhooks
```bash
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
python main.py --symbols AAPL MSFT SPY
```

### TimescaleDB (production)
```bash
export TIMESCALE_URL=postgresql://user:pass@host:5432/marketdata
# App auto-detects and uses TimescaleDB when this is set
```

---

## Architecture

```
├── src/
│   ├── fetcher.py              yfinance → Tick dataclass
│   ├── storage.py              SQLite (local/dev)
│   ├── timescale_store.py      TimescaleDB (production)
│   ├── signals.py              Stateless anomaly detectors
│   ├── alerts.py               Alert channel base + console/file
│   ├── webhooks.py             Discord + Slack webhook channels
│   ├── pipeline.py             Polling orchestration loop
│   ├── pnl_simulator.py        Paper trading P&L tracker
│   └── api.py                  REST API + OpenAPI/Swagger
├── dashboard/
│   ├── app.py                  Flask + background pipeline
│   └── templates/dashboard.html  Full trading UI
├── streamlit_app/app.py        Research dashboard
├── benchmarks/bench_pipeline.py  Latency profiling suite
├── tests/                      pytest test suite
├── .github/workflows/ci.yml    GitHub Actions CI
└── docker-compose.yml
```

---

## Running Tests
```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

## Running Benchmarks
```bash
python benchmarks/bench_pipeline.py
python benchmarks/bench_pipeline.py --ticks 10000 --symbols 10
```

---

## Tech Stack

Python 3.11+ · Flask · gunicorn · SQLite / TimescaleDB · yfinance · Chart.js · Streamlit · Plotly · pandas · pytest · Docker · GitHub Actions · Discord/Slack webhooks
