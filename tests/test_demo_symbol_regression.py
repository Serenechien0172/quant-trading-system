from datetime import date
from decimal import Decimal

import pytest

from dashboard import session_demo
from src.calendar import sessions
from src.config import SYMBOLS, Settings
from src.demo import MovingAverageCrossover, normalize_demo_symbols, simulate
from src.market_data import Bar


class ExactRangeHistory:
    """Deterministic prices spanning the exact reported range and its warm-up."""

    def fetch(self, symbol, start, end):
        result = []
        for i, day in enumerate(sessions(date.fromisoformat(start), date.fromisoformat(end))):
            phase = i % 100
            price = Decimal(100 + (phase if phase < 50 else 100 - phase))
            result.append(Bar(symbol, day, price, price + 1, price - 1, price, 1000))
        return result


def test_exact_cloud_range_passes_real_tickers_not_all_sentinel(monkeypatch):
    original = session_demo.demo_engine.simulate
    captured = []

    def checked(*args, **kwargs):
        # The former call passed "ALL" as a positional ticker to a single-symbol API.
        assert args == ("2025-01-01", "2026-10-16", Settings())
        assert kwargs["symbols"] == ("SPY", "QQQ", "AAPL", "NVDA", "MSFT")
        captured.append(kwargs["symbols"])
        return original(*args, **kwargs)

    monkeypatch.setattr(session_demo.demo_engine, "simulate", checked)
    report = session_demo.run_session_demo(
        "2025-01-01", "2026-10-16", Settings(), provider=ExactRangeHistory()
    )
    assert captured == [SYMBOLS]
    assert set(report.trades.symbol) == set(SYMBOLS)
    assert len(report.trades) > 0
    assert report.snapshots.iloc[-1].date.date().isoformat() == "2026-10-16"
    assert report.metrics["sharpe_ratio"] is not None


def test_old_marker_is_invalid_ticker_and_never_downloaded(tmp_path):
    class NoDownload:
        def fetch(self, *args):
            pytest.fail("Invalid ticker must fail before data download")

    with pytest.raises(ValueError, match="Unsupported demo symbol 'ALL'"):
        simulate(
            "2025-01-01", "2026-10-16", Settings(), "ALL", provider=NoDownload(), directory=tmp_path
        )
    assert not list(tmp_path.iterdir())


def test_normalization_preserves_strict_allowlist():
    assert normalize_demo_symbols((" spy ", "qqq", " AAPL", "nvda ", "MsFt")) == SYMBOLS
    assert MovingAverageCrossover(Settings(), " spy ").symbol == "SPY"
    for invalid in (("TSLA",), ("ALL",), ("SPY", "spy"), (), "SPY", (("Close", "SPY"),)):
        with pytest.raises(ValueError):
            normalize_demo_symbols(invalid)
