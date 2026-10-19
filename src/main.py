"""Command-line entry point."""

import argparse
import logging
import sqlite3
from datetime import date
from decimal import InvalidOperation

from src.analytics import performance
from src.calendar import latest_completed
from src.config import SYMBOLS, Settings, number
from src.market_data import YahooProvider, bars_on, update
from src.pipeline import run
from src.storage import connect


def portfolio(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT * FROM snapshots ORDER BY date DESC LIMIT 1").fetchone()
    if row is None:
        return "Paper account: $100,000 initial capital. Run pipeline to create the first snapshot."
    r = {key: number(row[key]) for key in row.keys() if key != "date"}
    r = {key: value if abs(value) > number("1e-20") else number(0) for key, value in r.items()}
    lines = [
        f"PAPER ONLY | As of {row['date']} (latest stored close)",
        f"Portfolio Value: ${r['equity']:,.2f}",
        f"Cash:            ${r['cash']:,.2f}",
        f"Positions:       ${r['position_value']:,.2f}",
        "",
        f"Session P&L:     {r['daily_pnl']:+,.2f} USD ({r['daily_return']:+.2%})",
        f"Total Return:    {r['cumulative_return']:+.2%}",
        f"SPY Return:      {r['spy_return']:+.2%} (total return)",
        f"Alpha vs SPY:    {r['cumulative_return'] - r['spy_return']:+.2%} (return difference)",
        f"Realized P&L:    ${r['realized']:,.2f}",
        f"Unrealized P&L:  ${r['unrealized']:,.2f}",
        f"Dividend Income: ${r['income']:,.2f}",
        "",
        "Symbol  Shares        Avg Entry*     Market Value    Unrealized",
    ]
    bars = bars_on(db, row["date"])
    for p in db.execute("SELECT * FROM positions ORDER BY symbol"):
        q, basis = number(p["quantity"]), number(p["basis"])
        if q:
            value = q * number(bars[p["symbol"]]["close"])
            lines.append(
                f"{p['symbol']:6} {q:12.6f} ${basis / q:12,.4f} ${value:13,.2f} ${value - basis:+,.2f}"
            )
    lines.append("* Average entry includes allocated buy fees.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper-only virtual trading account")
    parser.add_argument(
        "command",
        choices=["update", "pipeline", "portfolio", "trades", "performance", "history", "demo"],
    )
    parser.add_argument("--start", help="First session for a new account / market-data history")
    parser.add_argument("--strategy", choices=["cash", "dummy"], default=None)
    parser.add_argument("--end", help="Last date of a historical demo")
    parser.add_argument("--symbols", nargs="+", choices=SYMBOLS, default=list(SYMBOLS))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db = None
    try:
        settings = Settings.from_env()
        if args.command == "demo":
            from src.historical_simulation import simulate

            if not args.start or not args.end:
                raise ValueError("Demo requires --start and --end")
            path = simulate(
                start=args.start, end=args.end, settings=settings, symbols=tuple(args.symbols)
            )
            db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            print(f"HISTORICAL DEMO | {path}")
            print(portfolio(db))
            return 0
        db = connect(settings.database)
        if (
            args.command in ("update", "pipeline")
            and db.execute("SELECT 1 FROM sqlite_master WHERE name='demo_metadata'").fetchone()
        ):
            raise ValueError("Historical demo accounts cannot run the live paper pipeline")
        if args.command == "update":
            end = latest_completed()
            existing = db.execute("SELECT start_date FROM account").fetchone()
            start = args.start or (existing[0] if existing else end)
            date.fromisoformat(start)
            if start > end:
                raise ValueError("Start is after the latest completed session")
            update(db, YahooProvider(), start, end)
        elif args.command == "pipeline":
            run(db, latest_completed(), settings, args.strategy, args.start)
            print(portfolio(db))
        elif args.command == "portfolio":
            print(portfolio(db))
        elif args.command == "history":
            print(
                "Date        Equity (USD)    Daily P&L     Daily Return   Total Return   SPY Return"
            )
            for row in db.execute("SELECT * FROM snapshots ORDER BY date"):
                print(
                    f"{row['date']}  {number(row['equity']):14,.2f} "
                    f"{number(row['daily_pnl']):+12,.2f} "
                    f"{number(row['daily_return']):+13.2%} "
                    f"{number(row['cumulative_return']):+13.2%} "
                    f"{number(row['spy_return']):+11.2%}"
                )
        elif args.command == "trades":
            print("timestamp | symbol | side | quantity | price | cost | realized P&L")
            for row in db.execute("SELECT * FROM trades ORDER BY timestamp,id"):
                print(
                    " | ".join(
                        str(row[k])
                        for k in (
                            "timestamp",
                            "symbol",
                            "side",
                            "quantity",
                            "price",
                            "cost",
                            "realized",
                        )
                    )
                )
        else:
            for key, value in performance(db).items():
                formatted = (
                    "N/A"
                    if value is None
                    else (f"{value:.3f}" if key == "sharpe_ratio" else f"{value:+.2%}")
                )
                print(f"{key.replace('_', ' ').title():24} {formatted}")
        return 0
    except (ValueError, InvalidOperation, sqlite3.Error) as exc:
        logging.error("%s", exc)
        return 1
    except Exception:
        logging.exception("Pipeline failed; inspect provider/network availability")
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
