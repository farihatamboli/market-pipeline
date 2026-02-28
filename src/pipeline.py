"""
pipeline.py — Main orchestrator for the real-time market data pipeline.
Fetches price/volume data, stores it, and runs signal detection.
"""

import time
import logging
import argparse
from datetime import datetime

from .fetcher import MarketFetcher
from .storage import DataStore
from .signals import SignalDetector
from .alerts import AlertManager

logger = logging.getLogger(__name__)


def run_pipeline(symbols: list[str], interval_seconds: int = 60, max_iterations: int = None):
    """
    Main pipeline loop.

    Args:
        symbols: List of ticker symbols to track, e.g. ['AAPL', 'MSFT']
        interval_seconds: How often to poll for new data
        max_iterations: Stop after N iterations (None = run forever)
    """
    fetcher = MarketFetcher()
    store = DataStore()
    detector = SignalDetector()
    alerts = AlertManager()

    store.initialize()

    logger.info(f"Pipeline started | symbols={symbols} | interval={interval_seconds}s")

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            tick_time = datetime.utcnow()
            logger.info(f"[{tick_time.isoformat()}] Fetching {len(symbols)} symbols...")

            for symbol in symbols:
                try:
                    tick = fetcher.fetch(symbol)
                    if tick is None:
                        logger.warning(f"No data returned for {symbol}")
                        continue

                    store.insert_tick(tick)
                    history = store.get_recent(symbol, n=50)
                    fired_signals = detector.detect(tick, history)

                    for signal in fired_signals:
                        alerts.fire(signal)

                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}", exc_info=True)

            iteration += 1
            if max_iterations is None or iteration < max_iterations:
                logger.debug(f"Sleeping {interval_seconds}s...")
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("Pipeline interrupted by user.")
            break

    store.close()
    logger.info("Pipeline shut down cleanly.")
