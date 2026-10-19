"""Close-price simulation only; there is no real broker integration."""

import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from src.config import Settings, number
from src.portfolio import book_trade


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    quantity: Decimal


def execute(
    db: sqlite3.Connection,
    order: Order,
    price: Decimal,
    timestamp: str,
    order_id: str,
    settings: Settings,
) -> None:
    cost = settings.fixed_fee + number(order.quantity) * price * settings.fee_bps / Decimal(10000)
    book_trade(
        db,
        order_id=order_id,
        timestamp=timestamp,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=price,
        cost=cost,
    )
