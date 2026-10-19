from decimal import Decimal as D

import pytest
from conftest import FakeProvider

from src.market_data import Bar, update


def test_yahoo_nominal_split_normalization(monkeypatch):
    import pandas as pd
    import yfinance as yf

    from src.market_data import YahooProvider

    frame = pd.DataFrame(
        {
            "Open": [50, 50],
            "High": [50, 50],
            "Low": [50, 50],
            "Close": [50, 50],
            "Volume": [2000, 2000],
            "Dividends": [0.5, 0],
            "Stock Splits": [0, 2],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )

    class Ticker:
        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False
            assert kwargs["end"] == "2026-01-06"
            return frame

    monkeypatch.setattr(yf, "Ticker", lambda symbol: Ticker())
    bars = YahooProvider().fetch("SPY", "2026-01-02", "2026-01-05")
    assert bars[0].close == 100
    assert bars[0].dividend == 1
    assert bars[0].volume == 1000
    assert bars[1].close == 50
    assert bars[1].split == 2


def test_incremental_gap_repair_and_duplicate_prevention(db):
    provider = FakeProvider(["2026-01-02", "2026-01-05", "2026-01-06"])
    assert update(db, provider, "2026-01-02", "2026-01-05") == 10
    assert update(db, provider, "2026-01-02", "2026-01-05") == 0
    assert len(provider.calls) == 5
    assert update(db, provider, "2026-01-02", "2026-01-06") == 5
    db.execute("DELETE FROM bars WHERE symbol='SPY' AND date='2026-01-05'")
    assert update(db, provider, "2026-01-02", "2026-01-06") == 1
    assert db.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 15


def test_incomplete_download_is_atomic(db):
    with pytest.raises(ValueError, match="Incomplete"):
        update(db, FakeProvider(["2026-01-02"]), "2026-01-02", "2026-01-05")
    assert db.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity"])
def test_bad_bars(price):
    with pytest.raises(ValueError):
        Bar("SPY", "2026-01-02", *([D(price)] * 4), 100).validate()
