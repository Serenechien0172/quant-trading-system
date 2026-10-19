"""Incremental, gap-aware OHLCV ingestion with injectable data providers."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from src.calendar import sessions
from src.config import SYMBOLS, number
from src.storage import transaction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    dividend: Decimal = Decimal(0)
    split: Decimal = Decimal(0)

    def validate(self) -> None:
        date.fromisoformat(self.date)
        prices = [number(p) for p in (self.open, self.high, self.low, self.close)]
        if self.symbol not in SYMBOLS or min(prices) <= 0:
            raise ValueError("Invalid symbol or nonpositive OHLC")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Inconsistent OHLC")
        if self.volume < 0 or number(self.dividend) < 0 or number(self.split) < 0:
            raise ValueError("Invalid volume or corporate action")


class Provider(Protocol):
    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]: ...


class YahooProvider:
    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        import yfinance as yf

        yf.set_tz_cache_location(str(Path("data/yfinance-cache")))
        frame = yf.Ticker(symbol).history(
            start=start,
            end=(date.fromisoformat(end) + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
            raise_errors=True,
        )
        bars = []
        # Yahoo adjusts historical prices/dividends for splits even with auto_adjust=False.
        # Restore nominal prices within this fetched window before applying account splits.
        factor = Decimal(1)
        for stamp, row in reversed(list(frame.iterrows())):
            split = number(row.get("Stock Splits", 0))
            bars.append(
                Bar(
                    symbol,
                    stamp.date().isoformat(),
                    *(number(row[k]) * factor for k in ("Open", "High", "Low", "Close")),
                    int(number(row.Volume) / factor),
                    number(row.get("Dividends", 0)) * factor,
                    split,
                )
            )
            if split:
                factor *= split
        return list(reversed(bars))


def update(db: sqlite3.Connection, provider: Provider, start: str, end: str) -> int:
    expected = sessions(date.fromisoformat(start), date.fromisoformat(end))
    pending: list[Bar] = []
    for symbol in SYMBOLS:
        existing = {
            r[0]
            for r in db.execute(
                "SELECT date FROM bars WHERE symbol=? AND date BETWEEN ? AND ?",
                (symbol, start, end),
            )
        }
        missing = sorted(set(expected) - existing)
        if not missing:
            continue
        # Fetch through the latest session to undo any later splits in this window.
        downloaded = provider.fetch(symbol, missing[0], end)
        found = {b.date: b for b in downloaded if b.date in missing}
        if set(found) != set(missing):
            raise ValueError(
                f"Incomplete {symbol} data; missing {sorted(set(missing) - set(found))}"
            )
        for bar in found.values():
            bar.validate()
            if bar.symbol != symbol:
                raise ValueError("Provider returned the wrong symbol")
            pending.append(bar)
    with transaction(db):
        for b in pending:
            db.execute(
                "INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    b.symbol,
                    b.date,
                    str(b.open),
                    str(b.high),
                    str(b.low),
                    str(b.close),
                    b.volume,
                    str(b.dividend),
                    str(b.split),
                ),
            )
    log.info("Stored %d missing bars through %s", len(pending), end)
    return len(pending)


def bars_on(db: sqlite3.Connection, day: str) -> dict[str, sqlite3.Row]:
    result = {r["symbol"]: r for r in db.execute("SELECT * FROM bars WHERE date=?", (day,))}
    if set(result) != set(SYMBOLS):
        raise ValueError(f"Missing market prices for {day}; run update first")
    return result
