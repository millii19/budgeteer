from __future__ import annotations

import re
from datetime import date

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str, max_len: int) -> str:
    chunks = TOKEN_RE.findall(text.upper())
    joined = "".join(chunks)
    return joined[:max_len]


def build_base_transaction_code(
    recipient_name: str,
    category_chain: list[str],
    transaction_date: date,
) -> str:
    recipient = _tokenize(recipient_name, 8)

    parent = _tokenize(category_chain[0], 4) if category_chain else ""
    leaf = _tokenize(category_chain[-1], 4) if category_chain else ""
    day = transaction_date.strftime("%y%m%d")

    parts = [p for p in [recipient, parent, leaf, day] if p]
    if not parts:
        return f"EXP-{day}"
    return "-".join(parts)
