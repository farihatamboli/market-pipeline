"""
src/pipeline.py — Main polling loop (yfinance mode).
For real-time streaming use src/alpaca_stream.py instead.
"""

import time
import logging
from datetime import datetime

from .fetcher import MarketFetcher
from .storage import DataStore
from .signals import SignalDetector
from .alerts  import AlertManager

logger = logging.getLogger(__name__)


def run_pipeline(
    symbols:          list[str],
    interval_seconds: int  = 60,
    max_iterations:   int  = None,
):
    fetcher  = MarketFetcher()
    store    = DataStore()
    detector = SignalDetector()
    alerts   = AlertManager()
    store.initialize()

    logger.info(f"Pipeline started | symbols={symbols} | interval={interval_seconds}s")
    iteration = 0

    while max_iterations is None or iteration < max_iterations:
        try:
            logger.info(f"[{datetime.utcnow().isoformat()}] Fetching {len(symbols)} symbols...")
            for symbol in symbols:
                try:
                    tick = fetcher.fetch(symbol)
                    if tick is None:
                        continue
                    store.insert_tick(tick)
                    history = store.get_recent(symbol, n=50)
                    for sig in detector.detect(tick, history):
                        alerts.fire(sig)
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}", exc_info=True)

            iteration += 1
            if max_iterations is None or iteration < max_iterations:
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("Interrupted.")
            break

    store.close()
    logger.info("Pipeline shut down.")
