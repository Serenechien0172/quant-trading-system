"""Validated runtime configuration."""

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

INITIAL_CAPITAL = Decimal("100000")
SYMBOLS = ("SPY", "QQQ", "AAPL", "NVDA", "MSFT")


def number(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Numbers must be finite")
    return result


@dataclass(frozen=True)
class Settings:
    database: Path = Path("data/paper.db")
    fixed_fee: Decimal = Decimal("1")
    fee_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if number(self.fixed_fee) < 0 or number(self.fee_bps) < 0:
            raise ValueError("Fees must be nonnegative")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            Path(os.getenv("PAPER_DB", "data/paper.db")),
            number(os.getenv("PAPER_FIXED_FEE", "1")),
            number(os.getenv("PAPER_FEE_BPS", "0")),
        )
