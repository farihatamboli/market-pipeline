"""
storage.py — Lightweight SQLite storage for market ticks.

Why SQLite?
- Zero infrastructure — no Docker, no server
- Queryable with pandas or SQL for backtesting later
- Easy to swap for Postgres/TimescaleDB in production
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from .fetcher import Tick

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "ticks.db"


class DataStore:
    """Persists tick data to SQLite and retrieves historical windows."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def initialize(self):
        """Create the DB and ticks table if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT    NOT NULL,
                ts        TEXT    NOT NULL,
                price     REAL    NOT NULL,
                volume    INTEGER NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                vwap      REAL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_ts ON ticks(symbol, ts)")
        self.conn.commit()
        logger.info(f"DataStore initialized at {self.db_path}")

    def insert_tick(self, tick: Tick):
        """Persist a single tick to the database."""
        self.conn.execute("""
            INSERT INTO ticks (symbol, ts, price, volume, open, high, low, vwap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tick.symbol,
            tick.timestamp.isoformat(),
            tick.price,
            tick.volume,
            tick.open,
            tick.high,
            tick.low,
            tick.vwap,
        ))
        self.conn.commit()

    def get_recent(self, symbol: str, n: int = 50) -> list[Tick]:
        """Retrieve the N most recent ticks for a symbol (oldest first)."""
        cursor = self.conn.execute("""
            SELECT symbol, ts, price, volume, open, high, low, vwap
            FROM ticks
            WHERE symbol = ?
            ORDER BY ts DESC
            LIMIT ?
        """, (symbol, n))

        rows = cursor.fetchall()
        ticks = []
        for row in reversed(rows):  # oldest first
            ticks.append(Tick(
                symbol=row[0],
                timestamp=datetime.fromisoformat(row[1]),
                price=row[2],
                volume=row[3],
                open=row[4],
                high=row[5],
                low=row[6],
                vwap=row[7],
            ))
        return ticks

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("DataStore connection closed.")
