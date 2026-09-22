from __future__ import annotations

from decimal import Decimal


def format_minor(minor: int, currency: str = "CNY") -> str:
    sign = "-" if minor < 0 else ""
    abs_minor = abs(int(minor))
    major = Decimal(abs_minor) / Decimal(100)
    return f"{sign}{major:.2f}"
