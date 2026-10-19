from decimal import Decimal

import pytest

from src.config import SYMBOLS
from src.market_data import Bar
from src.storage import connect


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


def seed(db, day, price="100", dividend="0", split="0"):
    for symbol in SYMBOLS:
        db.execute(
            "INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol, day, price, price, price, price, 1000, dividend, split),
        )


class FakeProvider:
    def __init__(self, days):
        self.days = days
        self.calls = []

    def fetch(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return [
            Bar(symbol, day, *([Decimal(100)] * 4), 1000)
            for day in self.days
            if start <= day <= end
        ]
