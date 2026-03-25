from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def parse_amount_to_cents(raw: str) -> int:
    cleaned = raw.strip().replace(" ", "").replace(",", ".")
    if not cleaned:
        raise ValueError("Amount is required")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc

    if amount <= 0:
        raise ValueError("Amount must be greater than zero")

    cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def format_amount(cents: int, currency: str) -> str:
    major = Decimal(cents) / Decimal(100)
    return f"{major:.2f} {currency}"
