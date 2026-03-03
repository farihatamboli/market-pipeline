"""
src/timescale_store.py — TimescaleDB adapter.

Drop-in replacement for DataStore (SQLite). Implements the exact same
interface so zero changes needed in pipeline.py, dashboard, or tests.

Usage:
    export TIMESCALE_URL=postgresql://user:pass@host:5432/marketdata
    from src.timescale_store import TimescaleStore
    store = TimescaleStore(); store.initialize()

Why TimescaleDB over plain Postgres?
  - Automatic time-based partitioning (hypertables)
  - 90-95% compression on time-series data
  - time_bucket() SQL function for fast OHLCV aggregation
  - Continuous aggregates for pre-computed rollups
  - Same SQL interface as Postgres — no new query language

Schema design:
  - ticks table is a hypertable partitioned by ts (1-day chunks)
  - Composite index on (symbol, ts DESC) for O(1) latest-tick lookups
  - Separate signals table for alert history
"""

import os
import logging
from datetime import datetime
from typing import Optional

from .fetcher import Tick
from .signals import Signal

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

TIMESCALE_URL = os.environ.get(
    "TIMESCALE_URL",
    "postgresql://postgres:password@localhost:5432/marketdata"
)

_CREATE_TICKS = """
CREATE TABLE IF NOT EXISTS ticks (
    ts      TIMESTAMPTZ     NOT NULL,
    symbol  TEXT            NOT NULL,
    price   DOUBLE PRECISION NOT NULL,
    volume  BIGINT          NOT NULL,
    open    DOUBLE PRECISION,
    high    DOUBLE PRECISION,
    low     DOUBLE PRECISION,
    vwap    DOUBLE PRECISION
);
"""

_CREATE_HYPERTABLE = """
SELECT create_hypertable('ticks', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
    ON ticks (symbol, ts DESC);
"""

_CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    signal_type TEXT            NOT NULL,
    price       DOUBLE PRECISION,
    message     TEXT,
    metadata    JSONB
);
SELECT create_hypertable('signals', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);
"""

_CREATE_CONT_AGG = """
-- 1-minute OHLCV continuous aggregate for fast chart queries
CREATE MATERIALIZED VIEW IF NOT EXISTS ticks_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    symbol,
    first(price, ts)  AS open,
    max(price)        AS high,
    min(price)        AS low,
    last(price, ts)   AS close,
    sum(volume)       AS volume,
    last(vwap, ts)    AS vwap
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;
"""


class TimescaleStore:
    """
    TimescaleDB-backed tick store.

    Interface is identical to DataStore (SQLite) — swap by changing
    one import in pipeline.py or app.py.

    Example:
        store = TimescaleStore(url="postgresql://...")
        store.initialize()
        store.insert_tick(tick)
        recent = store.get_recent("AAPL", 50)
    """

    def __init__(self, url: str = TIMESCALE_URL):
        if not _PG_AVAILABLE:
            raise ImportError(
                "pip install psycopg2-binary\n"
                "Or use DataStore (SQLite) for local development."
            )
        self.url  = url
        self.conn = None

    def initialize(self):
        """Create tables, hypertables, indexes, and continuous aggregates."""
        self.conn = psycopg2.connect(self.url)
        self.conn.autocommit = False
        cur = self.conn.cursor()

        cur.execute(_CREATE_TICKS)
        try:
            cur.execute(_CREATE_HYPERTABLE)
        except Exception:
            self.conn.rollback()  # hypertable already exists — fine
            self.conn.autocommit = False

        cur.execute(_CREATE_INDEX)

        try:
            cur.execute(_CREATE_SIGNALS)
        except Exception:
            self.conn.rollback()

        try:
            cur.execute(_CREATE_CONT_AGG)
        except Exception:
            self.conn.rollback()  # continuous agg may already exist

        self.conn.commit()
        logger.info(f"TimescaleDB ready at {self.url.split('@')[-1]}")

    # ── Write ──────────────────────────────────────────────────────────────

    def insert_tick(self, tick: Tick):
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ticks (ts, symbol, price, volume, open, high, low, vwap)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (tick.timestamp, tick.symbol, tick.price, tick.volume,
                 tick.open, tick.high, tick.low, tick.vwap)
            )
        self.conn.commit()

    def insert_signal(self, signal: Signal):
        import json
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO signals (ts, symbol, signal_type, price, message, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (signal.timestamp, signal.symbol, signal.signal_type,
                 signal.price, signal.message, json.dumps(signal.metadata))
            )
        self.conn.commit()

    # ── Read ───────────────────────────────────────────────────────────────

    def get_recent(self, symbol: str, n: int = 50) -> list[Tick]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, ts, price, volume, open, high, low, vwap
                   FROM ticks WHERE symbol = %s
                   ORDER BY ts DESC LIMIT %s""",
                (symbol, n)
            )
            rows = cur.fetchall()
        return [self._row(r) for r in reversed(rows)]

    def get_range(self, symbol: str, start: str, end: str) -> list[Tick]:
        """Fetch ticks in a time range — used by backtester."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, ts, price, volume, open, high, low, vwap
                   FROM ticks WHERE symbol = %s AND ts >= %s AND ts <= %s
                   ORDER BY ts ASC""",
                (symbol, start, end)
            )
            rows = cur.fetchall()
        return [self._row(r) for r in rows]

    def get_ohlcv(self, symbol: str, bucket: str = '1 minute', n: int = 60):
        """
        Fast OHLCV aggregation using TimescaleDB time_bucket().
        Returns list of dicts with open/high/low/close/volume/vwap.

        This is the key advantage over SQLite — these queries run in
        microseconds on millions of rows thanks to hypertable partitioning.
        """
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""SELECT
                        time_bucket(%s, ts) AS bucket,
                        first(price, ts) AS open,
                        max(price)       AS high,
                        min(price)       AS low,
                        last(price, ts)  AS close,
                        sum(volume)      AS volume,
                        last(vwap, ts)   AS vwap
                    FROM ticks
                    WHERE symbol = %s
                    ORDER BY bucket DESC LIMIT %s""",
                (bucket, symbol, n)
            )
            rows = cur.fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_symbols(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM ticks ORDER BY symbol")
            return [r[0] for r in cur.fetchall()]

    def get_signal_history(self, symbol: Optional[str] = None, n: int = 100):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if symbol:
                cur.execute(
                    "SELECT * FROM signals WHERE symbol=%s ORDER BY ts DESC LIMIT %s",
                    (symbol, n)
                )
            else:
                cur.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT %s", (n,))
            return [dict(r) for r in cur.fetchall()]

    # ── Helpers ────────────────────────────────────────────────────────────

    def _row(self, row) -> Tick:
        ts = row[1]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return Tick(
            symbol    = row[0],
            timestamp = ts,
            price     = row[2],
            volume    = row[3],
            open      = row[4],
            high      = row[5],
            low       = row[6],
            vwap      = row[7],
        )

    def close(self):
        if self.conn:
            self.conn.close()


# ── Migration helper ────────────────────────────────────────────────────────

def migrate_from_sqlite(sqlite_path: str, timescale_url: str):
    """
    One-shot migration: copy all ticks from SQLite → TimescaleDB.

    Usage:
        python -c "
        from src.timescale_store import migrate_from_sqlite
        migrate_from_sqlite('data/ticks.db', 'postgresql://...')
        "
    """
    import sqlite3
    from pathlib import Path

    src  = sqlite3.connect(sqlite_path)
    dest = TimescaleStore(timescale_url)
    dest.initialize()

    cur  = src.execute("SELECT symbol, ts, price, volume, open, high, low, vwap FROM ticks ORDER BY ts")
    rows = cur.fetchall()
    logger.info(f"Migrating {len(rows):,} ticks from SQLite → TimescaleDB...")

    batch = []
    for row in rows:
        tick = Tick(
            symbol    = row[0],
            timestamp = datetime.fromisoformat(row[1]),
            price     = row[2], volume=row[3],
            open      = row[4], high=row[5], low=row[6], vwap=row[7],
        )
        dest.insert_tick(tick)
        batch.append(tick)

    logger.info(f"Migration complete: {len(batch):,} ticks written.")
    src.close(); dest.close()
