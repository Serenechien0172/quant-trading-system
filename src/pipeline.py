"""Replay unprocessed sessions in order; a session commits all or nothing."""

import logging
import sqlite3
from datetime import date
from decimal import Decimal

from src.calendar import close_timestamp, sessions
from src.config import Settings, number
from src.execution import execute
from src.market_data import bars_on
from src.portfolio import account, corporate_actions, initialize, valuation
from src.storage import transaction
from src.strategies import get_strategy

log = logging.getLogger(__name__)


def run(
    db: sqlite3.Connection,
    end: str,
    settings: Settings,
    strategy_name: str | None = None,
    start: str | None = None,
) -> int:
    existing = db.execute("SELECT * FROM account").fetchone()
    name = strategy_name or (existing["strategy"] if existing else "cash")
    strategy = get_strategy(name)
    start = start or (existing["start_date"] if existing else end)
    if existing and (name != existing["strategy"] or start != existing["start_date"]):
        raise ValueError("Account start and strategy are immutable; use a separate PAPER_DB")
    days = sessions(date.fromisoformat(start), date.fromisoformat(end))
    if not days or days[0] != start:
        raise ValueError("Start must be a trading session at or before the end date")
    count = 0
    for day in days:
        with transaction(db):
            if db.execute("SELECT 1 FROM snapshots WHERE date=?", (day,)).fetchone():
                continue
            bars = bars_on(db, day)
            first = db.execute("SELECT 1 FROM account").fetchone() is None
            if first:
                initialize(db, day, name, number(bars["SPY"]["close"]))
            else:
                corporate_actions(db, day, bars)
                a = account(db)
                # Total-return SPY benchmark: fractional units, dividends reinvested at close.
                units = number(a["spy_units"]) * (number(bars["SPY"]["split"]) or Decimal(1))
                units *= 1 + number(bars["SPY"]["dividend"]) / number(bars["SPY"]["close"])
                db.execute("UPDATE account SET spy_units=? WHERE id=1", (str(units),))
            for index, order in enumerate(strategy.orders(db, day)):
                execute(
                    db,
                    order,
                    number(bars[order.symbol]["close"]),
                    close_timestamp(day),
                    f"{name}:{day}:{index}",
                    settings,
                )
            a = account(db)
            value, unrealized = valuation(db, bars)
            equity = number(a["cash"]) + value
            last = db.execute("SELECT equity FROM snapshots ORDER BY date DESC LIMIT 1").fetchone()
            previous = number(last[0]) if last else number(a["initial"])
            pnl = equity - previous
            spy_return = (
                number(a["spy_units"]) * number(bars["SPY"]["close"]) / number(a["initial"]) - 1
            )
            if first:
                spy_return = Decimal(0)
            db.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    day,
                    a["cash"],
                    str(value),
                    str(equity),
                    str(pnl),
                    str(pnl / previous if previous else Decimal(0)),
                    str(equity / number(a["initial"]) - 1),
                    str(spy_return),
                    a["realized"],
                    str(unrealized),
                    a["income"],
                ),
            )
        count += 1
        log.info("Completed session %s, equity $%.2f, daily P&L %+.2f", day, equity, pnl)
    return count
