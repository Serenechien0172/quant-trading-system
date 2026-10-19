"""Long-only accounting using fee-inclusive average cost basis."""

import sqlite3
from decimal import Decimal

from src.config import INITIAL_CAPITAL, SYMBOLS, number


def initialize(db: sqlite3.Connection, day: str, strategy: str, spy_price: Decimal) -> None:
    db.execute(
        "INSERT INTO account VALUES (1,?,?,?,?,?,?,?)",
        (
            str(INITIAL_CAPITAL),
            str(INITIAL_CAPITAL),
            day,
            strategy,
            "0",
            "0",
            str(INITIAL_CAPITAL / spy_price),
        ),
    )


def account(db: sqlite3.Connection) -> sqlite3.Row:
    row = db.execute("SELECT * FROM account WHERE id=1").fetchone()
    if row is None:
        raise ValueError("Account not initialized; run pipeline")
    return row


def book_trade(
    db: sqlite3.Connection,
    *,
    order_id: str,
    timestamp: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    cost: Decimal,
) -> None:
    """Caller must own a transaction; account and ledger change together."""
    if not db.in_transaction:
        raise ValueError("Trades require an atomic transaction")
    quantity, price, cost = map(number, (quantity, price, cost))
    if symbol not in SYMBOLS or side not in ("BUY", "SELL"):
        raise ValueError("Invalid symbol or side")
    if quantity <= 0 or price <= 0 or cost < 0:
        raise ValueError("Invalid quantity, price or fee")
    if db.execute("SELECT 1 FROM trades WHERE order_id=?", (order_id,)).fetchone():
        raise ValueError("Duplicate order ID")
    a = account(db)
    cash = number(a["cash"])
    p = db.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
    owned, basis = (number(p["quantity"]), number(p["basis"])) if p else (Decimal(0), Decimal(0))
    realized = Decimal(0)
    if side == "BUY":
        debit = quantity * price + cost
        if debit > cash:
            raise ValueError("Insufficient cash")
        cash -= debit
        owned += quantity
        basis += debit
    else:
        if quantity > owned:
            raise ValueError("Cannot sell more shares than owned")
        proceeds = quantity * price - cost
        if cash + proceeds < 0:
            raise ValueError("Fee would make cash negative")
        removed_basis = basis if quantity == owned else basis * quantity / owned
        realized = proceeds - removed_basis
        cash += proceeds
        owned -= quantity
        basis -= removed_basis
    db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?)", (symbol, str(owned), str(basis)))
    db.execute(
        "UPDATE account SET cash=?, realized=? WHERE id=1",
        (str(cash), str(number(a["realized"]) + realized)),
    )
    db.execute(
        "INSERT INTO trades(order_id,timestamp,symbol,side,quantity,price,cost,realized) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (order_id, timestamp, symbol, side, str(quantity), str(price), str(cost), str(realized)),
    )


def corporate_actions(db: sqlite3.Connection, day: str, bars: dict[str, sqlite3.Row]) -> None:
    """Apply splits before dividends; dividends are credited on ex-date (simplification)."""
    income = Decimal(0)
    for p in db.execute("SELECT * FROM positions").fetchall():
        quantity = number(p["quantity"])
        b = bars[p["symbol"]]
        split, dividend = number(b["split"]), number(b["dividend"])
        if split:
            quantity *= split
            db.execute(
                "UPDATE positions SET quantity=? WHERE symbol=?", (str(quantity), p["symbol"])
            )
            db.execute(
                "INSERT INTO actions VALUES (?,?,?,?)", (day, p["symbol"], "split", str(split))
            )
        if dividend and quantity:
            credit = quantity * dividend
            income += credit
            db.execute(
                "INSERT INTO actions VALUES (?,?,?,?)", (day, p["symbol"], "dividend", str(credit))
            )
    a = account(db)
    db.execute(
        "UPDATE account SET cash=?, income=? WHERE id=1",
        (str(number(a["cash"]) + income), str(number(a["income"]) + income)),
    )


def valuation(db: sqlite3.Connection, bars: dict[str, sqlite3.Row]) -> tuple[Decimal, Decimal]:
    value, basis = Decimal(0), Decimal(0)
    for p in db.execute("SELECT * FROM positions"):
        value += number(p["quantity"]) * number(bars[p["symbol"]]["close"])
        basis += number(p["basis"])
    return value, value - basis
