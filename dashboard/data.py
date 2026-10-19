"""Read account reports without creating or mutating a database."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.analytics import performance
from src.config import number


@dataclass
class Report:
    snapshots: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float | None]
    strategy: str
    demo: dict | None


def load_report(path: Path, *, expect_demo: bool) -> Report:
    if not path.is_file():
        raise ValueError("No account database yet")
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        marker = db.execute("SELECT 1 FROM sqlite_master WHERE name='demo_metadata'").fetchone()
        if bool(marker) != expect_demo:
            raise ValueError("Account type does not match the selected mode")
        meta = (
            json.loads(db.execute("SELECT spec FROM demo_metadata").fetchone()[0])
            if marker
            else None
        )
        snapshots = pd.read_sql_query("SELECT * FROM snapshots ORDER BY date", db)
        if snapshots.empty:
            raise ValueError("No daily snapshots in this account")
        for column in snapshots.columns.difference(["date"]):
            snapshots[column] = snapshots[column].astype(float)
        snapshots["date"] = pd.to_datetime(snapshots["date"])
        last = snapshots.iloc[-1]
        positions = []
        for p in db.execute("SELECT * FROM positions ORDER BY symbol"):
            quantity = number(p["quantity"])
            if quantity:
                price = db.execute(
                    "SELECT close FROM bars WHERE symbol=? AND date=?",
                    (p["symbol"], last["date"].date().isoformat()),
                ).fetchone()
                if price is None:
                    raise ValueError("Missing position valuation price")
                basis = number(p["basis"])
                value = quantity * number(price[0])
                positions.append(
                    {
                        "Symbol": p["symbol"],
                        "Shares": float(quantity),
                        "Average entry ($)": float(basis / quantity),
                        "Market value ($)": float(value),
                        "Unrealized P&L ($)": float(value - basis),
                    }
                )
        trades = pd.read_sql_query(
            "SELECT timestamp,symbol,side,quantity,price,cost,realized FROM trades ORDER BY timestamp DESC,id DESC",
            db,
        )
        for col in ("quantity", "price", "cost", "realized"):
            trades[col] = trades[col].astype(float)
        return Report(
            snapshots,
            pd.DataFrame(positions),
            trades,
            performance(db),
            db.execute("SELECT strategy FROM account").fetchone()[0],
            meta,
        )
    finally:
        db.close()
