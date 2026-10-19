"""SQLite persistence. Monetary values are decimal strings, never binary floats."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
 symbol TEXT NOT NULL, date TEXT NOT NULL,
 open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
 volume INTEGER NOT NULL, dividend TEXT NOT NULL, split TEXT NOT NULL,
 PRIMARY KEY(symbol,date)
);
CREATE TABLE IF NOT EXISTS account (
 id INTEGER PRIMARY KEY CHECK(id=1), initial TEXT NOT NULL, cash TEXT NOT NULL,
 start_date TEXT NOT NULL, strategy TEXT NOT NULL, realized TEXT NOT NULL,
 income TEXT NOT NULL, spy_units TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
 symbol TEXT PRIMARY KEY, quantity TEXT NOT NULL, basis TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
 id INTEGER PRIMARY KEY, order_id TEXT NOT NULL UNIQUE, timestamp TEXT NOT NULL,
 symbol TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
 quantity TEXT NOT NULL, price TEXT NOT NULL, cost TEXT NOT NULL, realized TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
 date TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, amount TEXT NOT NULL,
 PRIMARY KEY(date,symbol,kind)
);
CREATE TABLE IF NOT EXISTS snapshots (
 date TEXT PRIMARY KEY, cash TEXT NOT NULL, position_value TEXT NOT NULL,
 equity TEXT NOT NULL, daily_pnl TEXT NOT NULL, daily_return TEXT NOT NULL,
 cumulative_return TEXT NOT NULL, spy_return TEXT NOT NULL,
 realized TEXT NOT NULL, unrealized TEXT NOT NULL, income TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


@contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
