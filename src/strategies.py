"""Strategy extension point. Dummy strategy has no alpha claim."""

import sqlite3
from decimal import Decimal
from typing import Protocol

from src.execution import Order


class Strategy(Protocol):
    name: str

    def orders(self, db: sqlite3.Connection, day: str) -> list[Order]: ...


class HoldCash:
    name = "cash"

    def orders(self, db: sqlite3.Connection, day: str) -> list[Order]:
        return []


class DummyBuyOne:
    """TEST ONLY: buy one SPY share once, then hold. No market-data signals."""

    name = "dummy"

    def orders(self, db: sqlite3.Connection, day: str) -> list[Order]:
        if db.execute("SELECT 1 FROM trades LIMIT 1").fetchone():
            return []
        return [Order("SPY", "BUY", Decimal(1))]


def get_strategy(name: str) -> Strategy:
    if name == "cash":
        return HoldCash()
    if name == "dummy":
        return DummyBuyOne()
    raise ValueError(f"Unknown strategy: {name}")
