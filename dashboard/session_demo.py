"""Self-contained cloud demo; only the resulting report survives in session state."""

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from dashboard.data import Report, load_report
from src.calendar import latest_completed, sessions
from src.config import SYMBOLS, Settings
from src.demo import HistoricalYahooProvider, simulate
from src.market_data import Bar, Provider


class DemoDataError(ValueError):
    """Unavailable or incomplete historical data."""


class DownloadedHistory:
    def __init__(self, bars: dict[str, list[Bar]]) -> None:
        self.bars = bars

    def fetch(self, symbol: str, start: str, end: str) -> list[Bar]:
        return [b for b in self.bars[symbol] if start <= b.date <= end]


def run_session_demo(
    start: str = "2025-01-01",
    end: str | None = None,
    settings: Settings | None = None,
    *,
    provider: Provider | None = None,
) -> Report:
    settings = settings or Settings.from_env()
    latest = latest_completed()
    end = end or latest
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if start_date > end_date or end > latest:
        raise ValueError(
            "Choose an ordered date range ending at or before the latest completed session."
        )
    requested = sessions(start_date, end_date)
    if not requested:
        raise ValueError("The date range contains no trading sessions.")
    warmup = (start_date - timedelta(days=160)).isoformat()
    source = provider or HistoricalYahooProvider(latest)
    bars = {}
    for symbol in SYMBOLS:
        try:
            bars[symbol] = source.fetch(symbol, warmup, end)
        except Exception as exc:
            raise DemoDataError(
                f"Yahoo Finance could not provide {symbol} data. It may be rate-limited or temporarily unavailable. Retry in a few minutes or choose an earlier end date."
            ) from exc
        if not bars[symbol]:
            raise DemoDataError(
                f"Yahoo Finance returned no data for {symbol}. Retry in a few minutes or choose another date range."
            )
    common = set(requested)
    for symbol in SYMBOLS:
        common &= {b.date for b in bars[symbol]}
    if not common or max(common) not in requested[-5:]:
        raise DemoDataError(
            "No recent common trading session is available for all five symbols. Retry later or choose an earlier end date."
        )
    actual_end = max(common)
    with TemporaryDirectory(prefix="quant-session-") as temporary:
        try:
            path = simulate(
                start,
                actual_end,
                settings,
                "ALL",
                provider=DownloadedHistory(bars),
                directory=Path(temporary),
            )
        except ValueError as exc:
            raise DemoDataError(
                f"Historical data could not be validated: {exc}. No partial result was saved; retry later or change the date range."
            ) from exc
        report = load_report(path, expect_demo=True)
    return report
