"""
main.py — CLI entry point for the market data pipeline.

Usage:
    python main.py --symbols AAPL MSFT TSLA --interval 60
    python main.py --symbols SPY QQQ --interval 30 --log-level DEBUG
"""

import argparse
import logging
import sys
from pathlib import Path

# Allow running as script or module
sys.path.insert(0, str(Path(__file__).parent))

from src.pipeline import run_pipeline


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
    parser = argparse.ArgumentParser(
        description="Real-time market data pipeline with anomaly detection"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=["AAPL", "MSFT", "SPY"],
        help="Ticker symbols to track (default: AAPL MSFT SPY)"
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Polling interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--iterations", type=int, default=None,
        help="Stop after N iterations (default: run forever)"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)

    print(f"""
╔══════════════════════════════════════════╗
║   Market Data Pipeline — Signal Detector ║
╚══════════════════════════════════════════╝
  Symbols  : {', '.join(args.symbols)}
  Interval : {args.interval}s
  Press Ctrl+C to stop
""")

    run_pipeline(
        symbols=args.symbols,
        interval_seconds=args.interval,
        max_iterations=args.iterations,
    )
