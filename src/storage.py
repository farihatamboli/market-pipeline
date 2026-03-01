"""
src/storage.py — SQLite tick store.

Zero infrastructure — no Docker, no server needed locally.
Swap DataStore for a TimescaleDB adapter in production by implementing
the same insert_tick / get_recent / get_range interface.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from .fetcher import Tick

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "ticks.db"


class DataStore:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def initialize(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol  TEXT    NOT NULL,
                ts      TEXT    NOT NULL,
                price   REAL    NOT NULL,
                volume  INTEGER NOT NULL,
                open    REAL,
                high    REAL,
                low     REAL,
                vwap    REAL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbol_ts ON ticks(symbol, ts)"
        )
        self.conn.commit()
        logger.info(f"DataStore ready at {self.db_path}")

    def insert_tick(self, tick: Tick):
        self.conn.execute("""
            INSERT INTO ticks (symbol, ts, price, volume, open, high, low, vwap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tick.symbol, tick.timestamp.isoformat(),
              tick.price, tick.volume,
              tick.open, tick.high, tick.low, tick.vwap))
        self.conn.commit()

    def get_recent(self, symbol: str, n: int = 50) -> list[Tick]:
        cur = self.conn.execute("""
            SELECT symbol, ts, price, volume, open, high, low, vwap
            FROM ticks WHERE symbol = ?
            ORDER BY ts DESC LIMIT ?
        """, (symbol, n))
        rows = cur.fetchall()
        return [self._row_to_tick(r) for r in reversed(rows)]

    def get_range(self, symbol: str, start: str, end: str) -> list[Tick]:
        """Fetch ticks between two ISO timestamps — used by backtester."""
        cur = self.conn.execute("""
            SELECT symbol, ts, price, volume, open, high, low, vwap
            FROM ticks WHERE symbol = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (symbol, start, end))
        return [self._row_to_tick(r) for r in cur.fetchall()]

    def get_symbols(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT DISTINCT symbol FROM ticks ORDER BY symbol"
        )
        return [r[0] for r in cur.fetchall()]

    def _row_to_tick(self, row) -> Tick:
        return Tick(
            symbol    = row[0],
            timestamp = datetime.fromisoformat(row[1]),
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
