from decimal import Decimal as D

import pytest
from conftest import seed

from src.config import Settings
from src.main import portfolio
from src.pipeline import run
from src.portfolio import account


def test_daily_pnl_and_benchmark(db):
    seed(db, "2026-01-02", "100")
    seed(db, "2026-01-05", "110")
    seed(db, "2026-01-06", "90")
    assert run(db, "2026-01-06", Settings(), "dummy", "2026-01-02") == 3
    rows = db.execute("SELECT * FROM snapshots ORDER BY date").fetchall()
    assert [D(r["equity"]) for r in rows] == [D(99999), D(100009), D(99989)]
    assert [D(r["daily_pnl"]) for r in rows] == [D(-1), D(10), D(-20)]
    assert D(rows[1]["daily_return"]) == D(10) / D(99999)
    assert D(rows[-1]["spy_return"]) == D("-.1")
    assert D(rows[-1]["cumulative_return"]) == D("-.00011")
    assert D(rows[-1]["unrealized"]) == -11
    assert run(db, "2026-01-06", Settings()) == 0
    assert db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    assert "As of 2026-01-06" in portfolio(db)
    assert "-20.00" in portfolio(db)


def test_split_and_dividend_preserve_economic_value(db):
    seed(db, "2026-01-02", "100")
    seed(db, "2026-01-05", "50", split="2")
    seed(db, "2026-01-06", "49", dividend="1")
    run(db, "2026-01-06", Settings(), "dummy", "2026-01-02")
    last = db.execute("SELECT * FROM snapshots ORDER BY date DESC").fetchone()
    assert D(last["equity"]) == 99999
    assert D(last["income"]) == 2
    assert D(last["spy_return"]) == pytest.approx(D(0), abs=D("1e-20"))
    assert D(db.execute("SELECT quantity FROM positions").fetchone()[0]) == 2
    assert D(last["equity"]) - 100000 == D(last["realized"]) + D(last["unrealized"]) + D(
        last["income"]
    )
    run(db, "2026-01-06", Settings())
    assert D(account(db)["income"]) == 2


def test_missing_prices_abort_session_and_resume(db):
    seed(db, "2026-01-02")
    with pytest.raises(ValueError, match="Missing"):
        run(db, "2026-01-05", Settings(), "dummy", "2026-01-02")
    assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
    seed(db, "2026-01-05", "120")
    assert run(db, "2026-01-05", Settings()) == 1
    assert db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_failed_initial_trade_rolls_back_initialization(db):
    seed(db, "2026-01-02", "200000")
    with pytest.raises(ValueError, match="cash"):
        run(db, "2026-01-02", Settings(), "dummy")
    assert db.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0


def test_cash_strategy_and_immutable_identity(db):
    seed(db, "2026-01-02")
    run(db, "2026-01-02", Settings())
    assert D(account(db)["cash"]) == 100000
    with pytest.raises(ValueError, match="immutable"):
        run(db, "2026-01-02", Settings(), "dummy")
    with pytest.raises(ValueError):
        run(db, "2026-01-02", Settings(), start="2026-01-03")
