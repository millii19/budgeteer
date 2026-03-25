from datetime import UTC, datetime, timedelta
from pathlib import Path

from budgeteer.storage import Storage


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "budgeteer.db")


def test_list_expenses_returns_newest_first(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    try:
        storage.save_expense(
            transaction_date="2026-03-24T10:11:12",
            recipient_name="Alpha Supplies",
            iban="DE00123456780000000001",
            amount_cents=1234,
            currency="EUR",
            category_chain=["Operations", "Balls"],
            comment="first",
            transaction_code="ALPHA-01",
        )
        storage.save_expense(
            transaction_date="2026-03-25T10:11:12",
            recipient_name="Beta Services",
            iban="DE00123456780000000002",
            amount_cents=5678,
            currency="EUR",
            category_chain=["Admin", "Fees"],
            comment="second",
            transaction_code="BETA-01",
        )

        rows = storage.list_expenses()

        assert len(rows) == 2
        assert rows[0]["recipient_name"] == "Beta Services"
        assert rows[1]["recipient_name"] == "Alpha Supplies"
    finally:
        storage.close()


def test_update_expense_updates_core_fields(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    try:
        storage.save_expense(
            transaction_date="2026-03-25T12:30:15",
            recipient_name="Alpha Supplies",
            iban="DE00123456780000000001",
            amount_cents=1234,
            currency="EUR",
            category_chain=["Operations", "Balls"],
            comment="old",
            transaction_code="ALPHA-01",
        )
        expense_id = int(storage.list_expenses()[0]["id"])

        updated = storage.update_expense(
            expense_id=expense_id,
            transaction_date="2026-03-26T16:00:00",
            recipient_name="Gamma Vendor",
            iban="DE00123456780000000003",
            amount_cents=9999,
            category_chain=["Travel", "Fuel"],
            comment="new",
        )

        row = storage.list_expenses()[0]
        assert updated is True
        assert row["transaction_date"] == "2026-03-26T16:00:00"
        assert row["recipient_name"] == "Gamma Vendor"
        assert row["iban"] == "DE00123456780000000003"
        assert row["amount_cents"] == 9999
        assert row["category_path"] == "Travel > Fuel"
        assert row["comment"] == "new"
    finally:
        storage.close()


def test_delete_expense_removes_record(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    try:
        storage.save_expense(
            transaction_date="2026-03-25T09:00:00",
            recipient_name="Alpha Supplies",
            iban="DE00123456780000000001",
            amount_cents=1234,
            currency="EUR",
            category_chain=["Operations", "Balls"],
            comment="to delete",
            transaction_code="ALPHA-01",
        )
        expense_id = int(storage.list_expenses()[0]["id"])

        deleted = storage.delete_expense(expense_id)

        assert deleted is True
        assert storage.list_expenses() == []
    finally:
        storage.close()


def test_list_expenses_created_between_filters_range(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    try:
        storage.save_expense(
            transaction_date="2026-03-25T09:00:00",
            recipient_name="Older Vendor",
            iban="DE00123456780000000001",
            amount_cents=1111,
            currency="EUR",
            category_chain=["Operations", "Balls"],
            comment="old",
            transaction_code="OLDER-01",
        )
        storage.save_expense(
            transaction_date="2026-03-25T10:00:00",
            recipient_name="Recent Vendor",
            iban="DE00123456780000000002",
            amount_cents=2222,
            currency="EUR",
            category_chain=["Operations", "Venue"],
            comment="recent",
            transaction_code="RECENT-01",
        )

        now = datetime.now(UTC)
        old_created = (now - timedelta(hours=30)).isoformat(timespec="seconds")
        recent_created = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        with storage.conn:
            storage.conn.execute(
                "UPDATE expenses SET created_at = ? WHERE transaction_code = ?",
                (old_created, "OLDER-01"),
            )
            storage.conn.execute(
                "UPDATE expenses SET created_at = ? WHERE transaction_code = ?",
                (recent_created, "RECENT-01"),
            )

        start = (now - timedelta(hours=24)).isoformat(timespec="seconds")
        end = now.isoformat(timespec="seconds")
        rows = storage.list_expenses_created_between(start, end)

        assert len(rows) == 1
        assert rows[0]["transaction_code"] == "RECENT-01"
    finally:
        storage.close()
