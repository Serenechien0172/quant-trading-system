from decimal import Decimal

import pandas as pd
import pytest
from test_demo import HistoricalFixture

from dashboard.session_demo import DemoDataError, run_session_demo
from src.config import SYMBOLS, Settings


def test_cloud_demo_uses_five_symbols_and_removes_temporary_db(tmp_path, monkeypatch):
    from dashboard import session_demo

    paths = []
    original = session_demo.demo_engine.simulate

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        paths.append(result)
        return result

    monkeypatch.setattr(session_demo.demo_engine, "simulate", tracked)
    live = tmp_path / "paper.db"
    live.write_bytes(b"live account unchanged")
    report = run_session_demo(
        "2025-01-01", "2025-04-01", Settings(database=live), provider=HistoricalFixture()
    )
    assert set(report.trades.symbol) == set(SYMBOLS)
    assert report.snapshots.iloc[0].equity == 100000
    assert report.snapshots.cash.min() >= 0
    assert (
        report.trades[report.trades.side == "BUY"].iloc[:5].eval("quantity * price + cost").max()
        <= 20000
    )
    assert live.read_bytes() == b"live account unchanged"
    assert paths and not paths[0].exists() and not paths[0].parent.exists()


def test_basket_future_invariance():
    short = run_session_demo("2025-01-01", "2025-03-03", provider=HistoricalFixture())
    long = run_session_demo("2025-01-01", "2025-04-01", provider=HistoricalFixture("2025-03-03"))
    pd.testing.assert_frame_equal(
        short.snapshots, long.snapshots[long.snapshots.date <= "2025-03-03"].reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(
        short.trades,
        long.trades[long.trades.timestamp.str[:10] <= "2025-03-03"].reset_index(drop=True),
    )


def test_missing_latest_bar_uses_common_completed_session():
    class Delayed(HistoricalFixture):
        def fetch(self, symbol, start, end):
            bars = super().fetch(symbol, start, end)
            return [b for b in bars if symbol != "NVDA" or b.date != "2025-04-01"]

    report = run_session_demo("2025-01-01", "2025-04-01", provider=Delayed())
    assert report.snapshots.iloc[-1].date.date().isoformat() == "2025-03-31"


def test_empty_and_interior_gap_have_useful_errors():
    class Empty:
        def fetch(self, *args):
            return []

    with pytest.raises(DemoDataError, match="SPY"):
        run_session_demo("2025-01-01", "2025-04-01", provider=Empty())

    class Gap(HistoricalFixture):
        def fetch(self, symbol, start, end):
            return [b for b in super().fetch(symbol, start, end) if b.date != "2025-02-03"]

    with pytest.raises(DemoDataError, match="No partial result"):
        run_session_demo("2025-01-01", "2025-04-01", provider=Gap())


def test_network_error_and_fee_aware_cash_guard():
    class Unavailable:
        def fetch(self, *args):
            raise ConnectionError("network")

    with pytest.raises(DemoDataError, match="rate-limited"):
        run_session_demo("2025-01-01", "2025-04-01", provider=Unavailable())
    report = run_session_demo(
        "2025-01-01",
        "2025-02-03",
        Settings(fixed_fee=Decimal(5), fee_bps=Decimal(10)),
        provider=HistoricalFixture(),
    )
    assert report.snapshots.cash.min() >= 0
