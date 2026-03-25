from __future__ import annotations

import re
from datetime import date, datetime

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str, max_len: int) -> str:
    chunks = TOKEN_RE.findall(text.upper())
    joined = "".join(chunks)
    return joined[:max_len]


def build_base_transaction_code(
    recipient_name: str,
    category_chain: list[str],
    transaction_date: date | datetime,
    comment: str = "",
) -> str:
    day = transaction_date.strftime("%y%m%d")

    parts = [p for p in [day, recipient_name, *category_chain, comment] if p]
    if not parts:
        return f"EXP-{day}"
    return " - ".join(parts)
