from datetime import datetime, timezone

import pytest
from conftest import seed

from src.analytics import performance
from src.calendar import close_timestamp, latest_completed
from src.config import Settings
from src.pipeline import run


def test_calendar_holidays_and_early_close():
    assert latest_completed(datetime(2026, 1, 1, 23, tzinfo=timezone.utc)) == "2025-12-31"
    assert latest_completed(datetime(2026, 1, 5, 20, tzinfo=timezone.utc)) == "2026-01-02"
    assert latest_completed(datetime(2026, 7, 2, 21, tzinfo=timezone.utc)) == "2026-07-02"
    assert "18:00:00" in close_timestamp("2026-11-27")
    assert "20:00:00" in close_timestamp("2026-07-06")
    assert "21:00:00" in close_timestamp("2026-01-05")


def test_zero_variance_and_no_sells(db):
    seed(db, "2026-01-02")
    run(db, "2026-01-02", Settings())
    m = performance(db)
    assert m["total_return"] == 0
    assert m["annualized_return"] is None
    assert m["sharpe_ratio"] is None
    assert m["win_rate"] is None
    seed(db, "2026-01-05")
    run(db, "2026-01-05", Settings())
    assert performance(db)["annualized_volatility"] == 0


def test_metrics_known_returns(db):
    seed(db, "2026-01-02")
    seed(db, "2026-01-05")
    seed(db, "2026-01-06")
    run(db, "2026-01-06", Settings(), start="2026-01-02")
    db.execute(
        "UPDATE snapshots SET daily_return='0.1', cumulative_return='0.1' WHERE date='2026-01-05'"
    )
    db.execute(
        "UPDATE snapshots SET daily_return='-0.1', cumulative_return='-0.01' WHERE date='2026-01-06'"
    )
    m = performance(db)
    assert m["total_return"] == -0.01
    assert m["annualized_return"] == pytest.approx(0.99**126 - 1)
    assert m["annualized_volatility"] == pytest.approx(0.1 * 252**0.5)
    assert m["sharpe_ratio"] == pytest.approx(0)
    assert m["maximum_drawdown"] == pytest.approx(-0.1)


def test_first_day_fee_in_drawdown(db):
    seed(db, "2026-01-02")
    run(db, "2026-01-02", Settings(), "dummy")
    assert performance(db)["maximum_drawdown"] == pytest.approx(-0.00001)


def test_win_rate_counts_net_profitable_sell_executions(db):
    from decimal import Decimal

    from src.portfolio import book_trade
    from src.storage import transaction

    seed(db, "2026-01-02")
    run(db, "2026-01-02", Settings())
    with transaction(db):
        for i, (side, quantity, price, cost) in enumerate(
            [
                ("BUY", 3, 100, 0),
                ("SELL", 1, 110, 1),
                ("SELL", 1, 100, 0),
                ("SELL", 1, 99, 0),
            ]
        ):
            book_trade(
                db,
                order_id=str(i),
                timestamp="2026-01-05T21:00:00Z",
                symbol="SPY",
                side=side,
                quantity=Decimal(quantity),
                price=Decimal(price),
                cost=Decimal(cost),
            )
    assert performance(db)["win_rate"] == pytest.approx(1 / 3)
