# 📈 Market Data Pipeline

A real-time market data pipeline with anomaly detection and alerting — built for extensibility and production-readiness.

## Features

- **Live data ingestion** via `yfinance` (free, no API key required)
- **SQLite persistence** — queryable tick store, easy to swap for TimescaleDB/Postgres
- **4 signal detectors**: price spike, volume surge, volatility burst, VWAP deviation
- **Multi-channel alerting**: console, file log, and a Slack stub
- **Clean module architecture**: fetcher → storage → signals → alerts
- **Full test suite** with `pytest`

## Quickstart

```bash
git clone https://github.com/YOUR_USERNAME/market-pipeline.git
cd market-pipeline
pip install -r requirements.txt

# Run with default symbols (AAPL, MSFT, SPY)
python main.py

# Custom symbols + faster polling
python main.py --symbols NVDA TSLA AMD --interval 30
```

## Architecture

```
main.py              CLI entrypoint
└── src/
    ├── pipeline.py  Orchestration loop
    ├── fetcher.py   yfinance data ingestion → Tick dataclass
    ├── storage.py   SQLite persistence layer
    ├── signals.py   Stateless anomaly detectors
    └── alerts.py    Multi-channel alert dispatcher
```

## Signals

| Signal | Trigger |
|--------|---------|
| `PRICE_SPIKE` | Price > 2.5σ from rolling mean |
| `VOLUME_SURGE` | Volume > 3× rolling average |
| `VOLATILITY_BURST` | H-L range > 2.5× rolling average |
| `VWAP_DEVIATION` | Price > 0.5% from session VWAP |

All thresholds are configurable via `SignalDetector(...)`.

## Running Tests

```bash
pytest tests/ -v
```

## Extending

**Add a new signal**: Implement a `_check_*` method in `signals.py` and call it from `detect()`.

**Add Slack alerts**: Set `SLACK_WEBHOOK_URL` env var and uncomment the Slack channel in `alerts.py`.

**Scale up**: Replace `DataStore` with a `TimescaleDB` adapter and `MarketFetcher` with an Alpaca WebSocket stream.

## Tech Stack

- Python 3.11+
- `yfinance` for market data
- `sqlite3` (stdlib) for storage
- `pytest` for testing

This project was created with the assistance of Claude Code
