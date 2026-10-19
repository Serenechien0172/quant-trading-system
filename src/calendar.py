"""NYSE sessions, including holidays, early closes and daylight saving time."""

from datetime import date, datetime, timedelta, timezone

import pandas_market_calendars as mcal


def sessions(start: date, end: date) -> list[str]:
    schedule = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    return [stamp.date().isoformat() for stamp in schedule.index]


def latest_completed(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Clock must include a timezone")
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=now.date() - timedelta(days=15), end_date=now.date()
    )
    finished = schedule[schedule.market_close <= now]
    if finished.empty:
        raise ValueError("No completed market session")
    return finished.index[-1].date().isoformat()


def close_timestamp(day: str) -> str:
    schedule = mcal.get_calendar("NYSE").schedule(start_date=day, end_date=day)
    if schedule.empty:
        raise ValueError(f"{day} is not a trading session")
    return schedule.iloc[0].market_close.isoformat()


def open_timestamp(day: str) -> str:
    schedule = mcal.get_calendar("NYSE").schedule(start_date=day, end_date=day)
    if schedule.empty:
        raise ValueError(f"{day} is not a trading session")
    return schedule.iloc[0].market_open.isoformat()
