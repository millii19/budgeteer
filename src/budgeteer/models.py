from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    language: str = Field(default="EN")
    currency: str = Field(default="EUR")
    database_path: str = Field(default=".budgeteer/budgeteer.db")
    categories: dict[str, Any]


class ExpenseInput(BaseModel):
    transaction_date: datetime
    recipient_name: str
    iban: str
    amount_cents: int
    category_chain: list[str]
    comment: str = ""


class Recipient(BaseModel):
    name: str
    iban: str
    last_used: str
