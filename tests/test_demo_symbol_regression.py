from datetime import date
from decimal import Decimal
from inspect import Parameter, signature
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dashboard import session_demo
from src.calendar import sessions
from src.config import SYMBOLS, Settings
from src.historical_simulation import MovingAverageCrossover, normalize_demo_symbols, simulate
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
        start="2025-01-01",
        end="2026-10-16",
        settings=Settings(),
        symbols=SYMBOLS,
        provider=ExactRangeHistory(),
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
            "2025-01-01",
            "2026-10-16",
            Settings(),
            symbols=("ALL",),
            provider=NoDownload(),
            directory=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_normalization_preserves_strict_allowlist():
    assert normalize_demo_symbols((" spy ", "qqq", " AAPL", "nvda ", "MsFt")) == SYMBOLS
    assert MovingAverageCrossover(Settings(), " spy ").symbol == "SPY"
    for invalid in (("TSLA",), ("ALL",), ("SPY", "spy"), (), "SPY", (("Close", "SPY"),)):
        with pytest.raises(ValueError):
            normalize_demo_symbols(invalid)


def test_simulator_and_dashboard_entrypoint_share_symbols_contract():
    for entrypoint in (simulate, session_demo.run_session_demo):
        parameters = signature(entrypoint).parameters
        assert "symbol" not in parameters
        assert parameters["symbols"].kind == Parameter.KEYWORD_ONLY
        assert parameters["symbols"].default == SYMBOLS


def test_dashboard_button_runs_actual_multi_symbol_simulator(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_DB", str(tmp_path / "absent-live.db"))
    monkeypatch.setattr(session_demo, "latest_completed", lambda: "2026-10-16")
    monkeypatch.setattr(
        session_demo.demo_engine, "HistoricalYahooProvider", lambda latest: ExactRangeHistory()
    )
    app = AppTest.from_file(str(Path("dashboard/app.py").resolve()), default_timeout=60).run()
    app.date_input[0].set_value(date(2025, 1, 1))
    app.date_input[1].set_value(date(2026, 10, 16))
    next(button for button in app.button if button.label == "Run Demo Simulation").click().run()
    assert not app.exception
    assert not app.error
    report = app.session_state["demo_report"]
    assert set(report.trades.symbol) == set(SYMBOLS)
    assert report.snapshots.iloc[-1].equity > 0
    assert len(app.metric) == 10
    assert report.metrics["sharpe_ratio"] is not None
    assert not (tmp_path / "absent-live.db").exists()
