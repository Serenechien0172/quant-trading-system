"""Isolated historical experiments using the existing daily accounting engine."""

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

from src.calendar import latest_completed, sessions
from src.config import SYMBOLS, Settings, number
from src.execution import Order
from src.market_data import Bar, Provider, YahooProvider, update
from src.pipeline import run
from src.portfolio import account
from src.storage import connect

DEMO_DIRECTORY = Path("data/demos")


def normalize_demo_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(symbols, tuple) or not symbols:
        raise ValueError("Demo symbols must be a nonempty tuple of ticker strings")
    normalized = []
    for value in symbols:
        if not isinstance(value, str) or value.strip().upper() not in SYMBOLS:
            raise ValueError(
                f"Unsupported demo symbol {value!r}; supported tickers: {', '.join(SYMBOLS)}"
            )
        normalized.append(value.strip().upper())
    if len(set(normalized)) != len(normalized):
        raise ValueError("Duplicate demo symbols are not allowed")
    return tuple(normalized)


class MovingAverageCrossover:
    """Prior-session 20/50 signal, next-open execution with whole-share sizing."""

    def __init__(self, settings: Settings, symbol: str = "SPY") -> None:
        symbol = normalize_demo_symbols((symbol,))[0]
        self.settings = settings
        self.symbol = symbol
        self.name = f"demo-sma20-50-{symbol}"

    def signal(self, db: sqlite3.Connection, day: str) -> int:
        rows = db.execute(
            "SELECT close,split FROM bars WHERE symbol=? AND date<? ORDER BY date DESC LIMIT 50",
            (self.symbol, day),
        ).fetchall()
        if len(rows) < 50:
            raise ValueError("Crossover requires 50 prior trading sessions of warm-up")
        # Express all past prices on the previous session's share basis using only known splits.
        factor = Decimal(1)
        closes = []
        for row in rows:
            closes.append(number(row["close"]) / factor)
            factor *= number(row["split"]) or Decimal(1)
        fast, slow = sum(closes[:20]) / 20, sum(closes) / 50
        return (fast > slow) - (fast < slow)

    def orders(self, db: sqlite3.Connection, day: str) -> list[Order]:
        a = account(db)
        # Inception is at the first close, matching the existing SPY benchmark baseline.
        if day == a["start_date"]:
            return []
        signal = self.signal(db, day)
        position = db.execute(
            "SELECT quantity FROM positions WHERE symbol=?", (self.symbol,)
        ).fetchone()
        owned = number(position[0]) if position else Decimal(0)
        if signal < 0 and owned:
            return [Order(self.symbol, "SELL", owned)]
        if signal > 0 and not owned:
            opening = db.execute(
                "SELECT open FROM bars WHERE symbol=? AND date=?", (self.symbol, day)
            ).fetchone()
            if opening is None:
                raise ValueError(f"Missing execution price for {day}")
            unit_cost = number(opening[0]) * (1 + self.settings.fee_bps / 10000)
            budget = max(Decimal(0), number(a["cash"]) - self.settings.fixed_fee)
            quantity = (budget / unit_cost).to_integral_value(rounding=ROUND_FLOOR)
            if quantity:
                return [Order(self.symbol, "BUY", quantity)]
        return []


class HistoricalYahooProvider:
    """Recover nominal prices even when Yahoo adjusted for splits after the requested end."""

    def __init__(self, through: str) -> None:
        self.through = through

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        return [b for b in YahooProvider().fetch(symbol, start, self.through) if b.date <= end]


class BasketMovingAverageCrossover:
    """Five independent SMA signals with 20% prior-equity entry budgets."""

    name = "demo-sma20-50-five-symbols"

    def __init__(self, settings: Settings, symbols: tuple[str, ...] = SYMBOLS) -> None:
        self.settings = settings
        self.symbols = normalize_demo_symbols(symbols)
        self.name = f"demo-sma20-50-{'-'.join(self.symbols)}"
        self.legs = {symbol: MovingAverageCrossover(settings, symbol) for symbol in self.symbols}

    def signal(self, db: sqlite3.Connection, day: str) -> dict[str, int]:
        return {symbol: leg.signal(db, day) for symbol, leg in self.legs.items()}

    def orders(self, db: sqlite3.Connection, day: str) -> list[Order]:
        a = account(db)
        if day == a["start_date"]:
            return []
        signals = self.signal(db, day)
        positions = {
            p["symbol"]: number(p["quantity"]) for p in db.execute("SELECT * FROM positions")
        }
        openings = {
            b["symbol"]: number(b["open"])
            for b in db.execute("SELECT symbol,open FROM bars WHERE date=?", (day,))
        }
        previous = db.execute(
            "SELECT equity FROM snapshots WHERE date<? ORDER BY date DESC LIMIT 1", (day,)
        ).fetchone()
        allocation = number(previous[0]) / len(self.symbols)
        available = number(a["cash"])
        orders = []
        # Sell first, so new entries can use the actual next-open net proceeds.
        for symbol in self.symbols:
            owned = positions.get(symbol, Decimal(0))
            if signals[symbol] < 0 and owned:
                proceeds = owned * openings[symbol]
                available += (
                    proceeds * (1 - self.settings.fee_bps / 10000) - self.settings.fixed_fee
                )
                orders.append(Order(symbol, "SELL", owned))
        for symbol in self.symbols:
            if signals[symbol] > 0 and not positions.get(symbol, Decimal(0)):
                budget = max(Decimal(0), min(allocation, available) - self.settings.fixed_fee)
                unit_cost = openings[symbol] * (1 + self.settings.fee_bps / 10000)
                quantity = (budget / unit_cost).to_integral_value(rounding=ROUND_FLOOR)
                if quantity:
                    orders.append(Order(symbol, "BUY", quantity))
                    available -= quantity * unit_cost + self.settings.fixed_fee
        return orders


def simulate(
    start: str,
    end: str,
    settings: Settings,
    symbol: str = "SPY",
    *,
    symbols: tuple[str, ...] | None = None,
    provider: Provider | None = None,
    directory: Path = DEMO_DIRECTORY,
) -> Path:
    """Build a fresh temporary account, publish only after a fully successful replay."""
    universe = normalize_demo_symbols(symbols if symbols is not None else (symbol,))
    strategy = (
        BasketMovingAverageCrossover(settings, universe)
        if len(universe) > 1
        else MovingAverageCrossover(settings, universe[0])
    )
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    latest = latest_completed()
    if start_date > end_date or end > latest:
        raise ValueError(
            "Demo dates must be ordered and end at or before the latest completed session"
        )
    days = sessions(start_date, end_date)
    if not days:
        raise ValueError("The demo range contains no trading sessions")
    spec = {
        "start": start,
        "end": end,
        "symbols": universe,
        "fixed_fee": str(settings.fixed_fee),
        "fee_bps": str(settings.fee_bps),
        "version": 2,
    }
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    target = directory / f"sma-{'-'.join(universe)}-{start}-{end}-{key}.db"
    if target.resolve() in {settings.database.resolve(), Path("data/paper.db").resolve()}:
        raise ValueError("Demo destination must never be the live paper account")
    if target.exists():
        if settings.database.exists() and os.path.samefile(target, settings.database):
            raise ValueError("Demo destination aliases the live account")
        with sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True) as existing:
            if existing.execute("SELECT spec FROM demo_metadata").fetchone()[0] != json.dumps(
                spec, sort_keys=True
            ):
                raise ValueError("Existing destination is not this demo")
    directory.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".building-", suffix=".db", dir=directory)
    os.close(handle)
    temporary = Path(temp_name)
    db = None
    try:
        db = connect(temporary)
        warmup = (start_date - timedelta(days=160)).isoformat()
        update(db, provider or HistoricalYahooProvider(latest), warmup, days[-1])
        strategy.signal(db, days[0])  # Validate warm-up before creating the account.
        run(db, days[-1], settings, start=days[0], strategy=strategy, fill_at="open")
        db.execute("CREATE TABLE demo_metadata (spec TEXT NOT NULL)")
        db.execute("INSERT INTO demo_metadata VALUES (?)", (json.dumps(spec, sort_keys=True),))
        db.close()
        db = None
        os.replace(temporary, target)
        return target
    finally:
        if db is not None:
            db.close()
        temporary.unlink(missing_ok=True)
