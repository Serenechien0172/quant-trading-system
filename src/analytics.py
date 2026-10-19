"""Performance statistics from persisted daily returns, including initial fees."""

import math
import sqlite3
import statistics

from src.config import number


def performance(db: sqlite3.Connection) -> dict[str, float | None]:
    rows = db.execute("SELECT * FROM snapshots ORDER BY date").fetchall()
    if not rows:
        raise ValueError("No snapshots; run pipeline first")
    returns = [float(number(r["daily_return"])) for r in rows]
    total = float(number(rows[-1]["cumulative_return"]))
    vol = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else None
    # First row is inception-close accounting, not a full invested session.
    periods = len(rows) - 1
    annual = math.expm1(math.log1p(total) * 252 / periods) if periods and total > -1 else None
    if periods and total == -1:
        annual = -1.0
    peak, drawdown = 1.0, 0.0
    for row in rows:
        growth = 1 + float(number(row["cumulative_return"]))
        peak = max(peak, growth)
        drawdown = min(drawdown, growth / peak - 1)
    sells = [number(r[0]) for r in db.execute("SELECT realized FROM trades WHERE side='SELL'")]
    return {
        "total_return": total,
        "annualized_return": annual,
        "annualized_volatility": vol,
        "sharpe_ratio": statistics.mean(returns) * 252 / vol if vol else None,
        "maximum_drawdown": drawdown,
        "win_rate": sum(p > 0 for p in sells) / len(sells) if sells else None,
    }
