from decimal import Decimal as D

import pytest

from src.config import Settings
from src.execution import Order, execute
from src.portfolio import account, book_trade, initialize
from src.storage import transaction


def trade(db, side="BUY", quantity="10", price="100", cost="1", order_id="one", **kwargs):
    book_trade(
        db,
        order_id=order_id,
        timestamp="2026-01-02T21:00:00+00:00",
        symbol="SPY",
        side=side,
        quantity=D(quantity),
        price=D(price),
        cost=D(cost),
        **kwargs,
    )


def setup(db):
    initialize(db, "2026-01-02", "cash", D(100))


def test_buy_partial_sell_full_close(db):
    with transaction(db):
        setup(db)
        trade(db)
        trade(db, quantity="10", price="120", order_id="two")
    p = db.execute("SELECT * FROM positions").fetchone()
    assert D(p["basis"]) == D(2202)
    assert D(account(db)["cash"]) == D(97798)
    with transaction(db):
        trade(db, side="SELL", quantity="5", price="130", order_id="three")
    assert D(account(db)["realized"]) == D("98.5")
    assert D(db.execute("SELECT basis FROM positions").fetchone()[0]) == D("1651.5")
    with transaction(db):
        trade(db, side="SELL", quantity="15", price="90", order_id="four")
    assert D(account(db)["realized"]) == D(-204)
    assert D(account(db)["cash"]) == D(99796)
    assert D(db.execute("SELECT basis FROM positions").fetchone()[0]) == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": "1000"},
        {"side": "SELL"},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"price": "0"},
        {"price": "NaN"},
        {"cost": "-1"},
        {"side": "SHORT"},
        {"quantity": "Infinity"},
    ],
)
def test_invalid_order_preserves_account(db, kwargs):
    setup(db)
    with pytest.raises(ValueError), transaction(db):
        trade(db, **kwargs)
    assert D(account(db)["cash"]) == 100000
    assert db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_duplicate_order_rejected(db):
    setup(db)
    with transaction(db):
        trade(db)
    with pytest.raises(ValueError, match="Duplicate"), transaction(db):
        trade(db)
    assert D(account(db)["cash"]) == 98999


def test_fees_and_sell_fee_cash_guard(db):
    setup(db)
    with transaction(db):
        execute(
            db,
            Order("SPY", "BUY", D(10)),
            D(100),
            "2026-01-02",
            "fee",
            Settings(fixed_fee=D(2), fee_bps=D(10)),
        )
    assert D(account(db)["cash"]) == 98997
    with pytest.raises(ValueError, match="negative"), transaction(db):
        trade(db, side="SELL", cost="200000", order_id="bad")


def test_transaction_rolls_back_earlier_trade(db):
    setup(db)
    with pytest.raises(ValueError), transaction(db):
        trade(db)
        trade(db, side="SELL", quantity="11", order_id="bad")
    assert D(account(db)["cash"]) == 100000
    assert db.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


def test_requires_transaction(db):
    setup(db)
    with pytest.raises(ValueError, match="transaction"):
        trade(db)


@pytest.mark.parametrize("fee", ["-1", "NaN", "Infinity"])
def test_invalid_fee_config(fee):
    with pytest.raises(ValueError):
        Settings(fixed_fee=D(fee))
