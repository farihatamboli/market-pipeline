"""
main.py — CLI entry point.

Usage:
    # yfinance polling (default)
    python main.py --symbols AAPL MSFT SPY --interval 60

    # Alpaca real-time stream
    python main.py --symbols AAPL MSFT SPY --stream alpaca
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def setup_logging(level: str):
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "pipeline.log"),
        ],
    )


def parse_args():
    p = argparse.ArgumentParser(description="Market Data Pipeline")
    p.add_argument("--symbols",    nargs="+",  default=["AAPL", "MSFT", "SPY"])
    p.add_argument("--interval",   type=int,   default=60,    help="Poll interval in seconds (yfinance mode)")
    p.add_argument("--iterations", type=int,   default=None,  help="Stop after N iterations")
    p.add_argument("--stream",     choices=["yfinance", "alpaca"], default="yfinance")
    p.add_argument("--log-level",  default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"])
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)

    print(f"""
╔══════════════════════════════════════════╗
║   Market Data Pipeline — Signal Detector ║
╚══════════════════════════════════════════╝
  Symbols : {', '.join(args.symbols)}
  Mode    : {args.stream}
  Press Ctrl+C to stop
""")

    if args.stream == "alpaca":
        from src.alpaca_stream import AlpacaStream
        from src.storage import DataStore
        from src.signals import SignalDetector
        from src.alerts  import AlertManager

        store    = DataStore(); store.initialize()
        detector = SignalDetector()
        alerts   = AlertManager()

        def on_tick(tick):
            store.insert_tick(tick)
            history = store.get_recent(tick.symbol, 50)
            for sig in detector.detect(tick, history):
                alerts.fire(sig)

        stream = AlpacaStream(symbols=args.symbols, on_tick=on_tick)
        stream.run()

    else:
        from src.pipeline import run_pipeline
        run_pipeline(
            symbols          = args.symbols,
            interval_seconds = args.interval,
            max_iterations   = args.iterations,
        )
