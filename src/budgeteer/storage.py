from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipients (
                name TEXT PRIMARY KEY,
                iban TEXT NOT NULL,
                last_used TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_date TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                iban TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL,
                category_path TEXT NOT NULL,
                comment TEXT,
                transaction_code TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_recipients_last_used ON recipients(last_used DESC);
            CREATE INDEX IF NOT EXISTS idx_expenses_transaction_date ON expenses(transaction_date);
            """
        )
        self.conn.commit()

    def list_recipient_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM recipients ORDER BY datetime(last_used) DESC, name ASC"
        ).fetchall()
        return [str(row["name"]) for row in rows]

    def get_recipient(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT name, iban, last_used FROM recipients WHERE lower(name) = lower(?)",
            (name,),
        ).fetchone()

    def upsert_recipient(self, name: str, iban: str) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO recipients(name, iban, last_used)
            VALUES (?, ?, ?)
            ON CONFLICT(name)
            DO UPDATE SET iban = excluded.iban, last_used = excluded.last_used
            """,
            (name, iban, now),
        )

    def next_transaction_code(self, base_code: str) -> str:
        existing = self.conn.execute(
            "SELECT transaction_code FROM expenses WHERE transaction_code LIKE ?",
            (f"{base_code}%",),
        ).fetchall()
        used = {str(row["transaction_code"]) for row in existing}
        if base_code not in used:
            return base_code

        counter = 2
        while True:
            candidate = f"{base_code}-{counter:02d}"
            if candidate not in used:
                return candidate
            counter += 1

    def save_expense(
        self,
        transaction_date: str,
        recipient_name: str,
        iban: str,
        amount_cents: int,
        currency: str,
        category_chain: list[str],
        comment: str,
        transaction_code: str,
    ) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        category_path = " > ".join(category_chain)

        with self.conn:
            self.upsert_recipient(recipient_name, iban)
            self.conn.execute(
                """
                INSERT INTO expenses(
                    transaction_date, recipient_name, iban, amount_cents,
                    currency, category_path, comment, transaction_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_date,
                    recipient_name,
                    iban,
                    amount_cents,
                    currency,
                    category_path,
                    comment,
                    transaction_code,
                    now,
                ),
            )

    def list_expenses(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT id, transaction_date, recipient_name, iban, amount_cents, currency,
                   category_path, comment, transaction_code, created_at
            FROM expenses
            ORDER BY datetime(created_at) DESC, id DESC
            """
        ).fetchall()

    def list_expenses_created_between(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT id, transaction_date, recipient_name, iban, amount_cents, currency,
                   category_path, comment, transaction_code, created_at
            FROM expenses
            WHERE datetime(created_at) >= datetime(?)
              AND datetime(created_at) < datetime(?)
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (start_iso, end_iso),
        ).fetchall()

    def update_expense(
        self,
        expense_id: int,
        transaction_date: str,
        recipient_name: str,
        iban: str,
        amount_cents: int,
        category_chain: list[str],
        comment: str,
    ) -> bool:
        category_path = " > ".join(category_chain)

        with self.conn:
            self.upsert_recipient(recipient_name, iban)
            result = self.conn.execute(
                """
                UPDATE expenses
                SET transaction_date = ?,
                    recipient_name = ?,
                    iban = ?,
                    amount_cents = ?,
                    category_path = ?,
                    comment = ?
                WHERE id = ?
                """,
                (
                    transaction_date,
                    recipient_name,
                    iban,
                    amount_cents,
                    category_path,
                    comment,
                    expense_id,
                ),
            )

        return result.rowcount > 0

    def delete_expense(self, expense_id: int) -> bool:
        with self.conn:
            result = self.conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return result.rowcount > 0

    def close(self) -> None:
        self.conn.close()
