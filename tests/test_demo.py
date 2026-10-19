import sqlite3
from datetime import date
from decimal import Decimal as D

import pytest
from conftest import seed

from src.calendar import sessions
from src.config import Settings
from src.demo import MovingAverageCrossover, simulate
from src.market_data import Bar
from src.portfolio import account, initialize


class HistoricalFixture:
    def __init__(self, change_after=None):
        self.change_after = change_after

    def fetch(self, symbol, start, end):
        result = []
        all_days = sessions(date(2024, 1, 1), date(2025, 6, 30))
        for index, day in enumerate(all_days):
            if start <= day <= end:
                phase = index % 100
                price = D(100 + (phase if phase < 50 else 100 - phase))
                if self.change_after and day > self.change_after:
                    price *= 3
                result.append(Bar(symbol, day, price, price + 1, price - 1, price, 1000))
        return result


@pytest.fixture
def signal_account(db):
    days = sessions(date(2024, 9, 1), date(2025, 1, 31))
    for i, day in enumerate(days):
        seed(db, day, "100" if i < 30 else "120")
    initialize(db, days[49], "demo-sma20-50-SPY", D(120))
    return db, days


def test_signal_never_reads_execution_day_close_or_future(signal_account):
    db, days = signal_account
    strategy = MovingAverageCrossover(Settings())
    before = strategy.orders(db, days[50])
    assert before and before[0].side == "BUY"
    db.execute("UPDATE bars SET close='0.01' WHERE date>=?", (days[50],))
    assert strategy.orders(db, days[50]) == before
    assert strategy.signal(db, days[50]) == 1


def test_warmup_ties_and_inception(signal_account):
    db, days = signal_account
    strategy = MovingAverageCrossover(Settings())
    with pytest.raises(ValueError, match="50 prior"):
        strategy.signal(db, days[20])
    assert strategy.orders(db, days[49]) == []
    db.execute("UPDATE bars SET close='100'")
    assert strategy.signal(db, days[50]) == 0
    assert strategy.orders(db, days[50]) == []


def test_open_gap_sizing_respects_cash_and_fees(signal_account):
    db, days = signal_account
    strategy = MovingAverageCrossover(Settings(fixed_fee=D(5), fee_bps=D(10)))
    db.execute("UPDATE bars SET open='200' WHERE date=?", (days[50],))
    order = strategy.orders(db, days[50])[0]
    assert order.quantity == 499
    assert order.quantity * D(200) * D("1.001") + 5 <= D(account(db)["cash"])


def test_known_split_does_not_create_false_bear_signal(signal_account):
    db, days = signal_account
    db.execute("UPDATE bars SET close='100'")
    db.execute("UPDATE bars SET close='50' WHERE date>=?", (days[40],))
    db.execute("UPDATE bars SET split='2' WHERE date=?", (days[40],))
    assert MovingAverageCrossover(Settings()).signal(db, days[50]) == 0


def read_rows(path, table):
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_simulation_reuses_engine_and_preserves_live(tmp_path):
    live = tmp_path / "paper.db"
    live.write_bytes(b"untouched live account")
    settings = Settings(database=live)
    path = simulate(
        "2025-01-01",
        "2025-04-01",
        settings,
        provider=HistoricalFixture(),
        directory=tmp_path / "demos",
    )
    assert live.read_bytes() == b"untouched live account"
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM snapshots ORDER BY date").fetchall()
        assert rows[0]["date"] == "2025-01-02"
        assert D(rows[0]["equity"]) == 100000
        assert len(rows) == len(sessions(date(2025, 1, 1), date(2025, 4, 1)))
        assert all(D(r["cash"]) >= 0 for r in rows)
        for r in rows:
            assert D(r["equity"]) == D(r["cash"]) + D(r["position_value"])
            assert D(r["equity"]) - 100000 == pytest.approx(
                D(r["realized"]) + D(r["unrealized"]) + D(r["income"]), abs=D("1e-18")
            )
        trades = db.execute("SELECT * FROM trades ORDER BY timestamp").fetchall()
        assert {t["side"] for t in trades} == {"BUY", "SELL"}
        for t in trades:
            assert "14:30:00" in t["timestamp"] or "13:30:00" in t["timestamp"]
            assert D(t["price"]) == D(
                db.execute(
                    "SELECT open FROM bars WHERE symbol=? AND date=?",
                    (t["symbol"], t["timestamp"][:10]),
                ).fetchone()[0]
            )
    first = read_rows(path, "snapshots")
    simulate(
        "2025-01-01",
        "2025-04-01",
        settings,
        provider=HistoricalFixture(),
        directory=tmp_path / "demos",
    )
    assert read_rows(path, "snapshots") == first


def test_future_changes_do_not_change_historical_results(tmp_path):
    settings = Settings(database=tmp_path / "live.db")
    short = simulate(
        "2025-01-01",
        "2025-03-03",
        settings,
        provider=HistoricalFixture(),
        directory=tmp_path / "short",
    )
    long = simulate(
        "2025-01-01",
        "2025-04-01",
        settings,
        provider=HistoricalFixture("2025-03-03"),
        directory=tmp_path / "long",
    )
    assert read_rows(short, "snapshots") == [
        r for r in read_rows(long, "snapshots") if r[0] <= "2025-03-03"
    ]
    assert read_rows(short, "trades") == [
        r for r in read_rows(long, "trades") if r[2][:10] <= "2025-03-03"
    ]


def test_bad_range_and_failed_build_leave_no_account(tmp_path):
    with pytest.raises(ValueError):
        simulate("2025-02-01", "2025-01-01", Settings(), directory=tmp_path)

    class Broken:
        def fetch(self, *args):
            return []

    with pytest.raises(ValueError, match="Incomplete"):
        simulate("2025-01-01", "2025-02-01", Settings(), provider=Broken(), directory=tmp_path)
    assert not list(tmp_path.glob("*.db"))


def test_failed_rebuild_preserves_demo_and_live_alias_is_rejected(tmp_path):
    settings = Settings(database=tmp_path / "live.db")
    path = simulate(
        "2025-01-01", "2025-02-01", settings, provider=HistoricalFixture(), directory=tmp_path
    )
    original = path.read_bytes()

    class Broken:
        def fetch(self, *args):
            raise RuntimeError("Data unavailable")

    with pytest.raises(RuntimeError):
        simulate("2025-01-01", "2025-02-01", settings, provider=Broken(), directory=tmp_path)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="live paper"):
        simulate(
            "2025-01-01",
            "2025-02-01",
            Settings(database=path),
            provider=HistoricalFixture(),
            directory=tmp_path,
        )


def test_live_cli_rejects_demo_database(tmp_path, monkeypatch):
    import sys

    from src.main import main

    path = simulate(
        "2025-01-01", "2025-02-01", Settings(), provider=HistoricalFixture(), directory=tmp_path
    )
    original = path.read_bytes()
    monkeypatch.setenv("PAPER_DB", str(path))
    for command in ("update", "pipeline"):
        monkeypatch.setattr(sys, "argv", ["paper", command])
        assert main() == 1
    assert path.read_bytes() == original
