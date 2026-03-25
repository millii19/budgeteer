from __future__ import annotations

from typing import Any

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from budgeteer.interactive_components.prompts import (
    _amount_input_from_cents,
    _mask_iban,
    _parse_category_path,
    _prompt_amount_cents,
    _prompt_comment,
    _prompt_datetime,
    _prompt_recipient,
    _select_category_chain,
)
from budgeteer.models import AppConfig
from budgeteer.parsing import format_amount
from budgeteer.storage import Storage

console = Console()


def _history_choice_label(row: Any) -> str:
    """Build a compact one-line label for an expense history choice."""
    return (
        f"#{row['id']} | {row['transaction_date']} | {row['recipient_name']} | "
        f"{format_amount(int(row['amount_cents']), str(row['currency']))} | {row['category_path']}"
    )


def _print_history_details(row: Any) -> None:
    """Print a detailed panel for a single expense history record."""
    table = Table(show_header=False, box=None)
    table.add_row("ID", str(row["id"]))
    table.add_row("Recorded at", str(row["created_at"]))
    table.add_row("Transaction datetime", str(row["transaction_date"]))
    table.add_row("Recipient", str(row["recipient_name"]))
    table.add_row("IBAN", _mask_iban(str(row["iban"])))
    table.add_row("Amount", format_amount(int(row["amount_cents"]), str(row["currency"])))
    table.add_row("Category", str(row["category_path"]))
    table.add_row("Comment", str(row["comment"] or "-"))
    table.add_row("Transaction code", str(row["transaction_code"]))
    console.print(Panel(table, title="Expense Record", expand=False))


def _edit_expense_flow(config: AppConfig, storage: Storage, row: Any) -> bool:
    """Run the interactive edit flow for a single stored expense."""
    tx_datetime = _prompt_datetime(str(row["transaction_date"]))
    recipient_name, iban = _prompt_recipient(
        storage,
        default_name=str(row["recipient_name"]),
        default_iban=str(row["iban"]),
    )
    amount_cents = _prompt_amount_cents(
        config.currency,
        default_value=_amount_input_from_cents(int(row["amount_cents"])),
    )

    current_category = str(row["category_path"])
    keep_category = questionary.confirm(
        f"Keep category '{current_category}'?",
        default=True,
    ).ask()
    if keep_category is None:
        raise KeyboardInterrupt
    if keep_category:
        category_chain = _parse_category_path(current_category)
    else:
        category_chain = _select_category_chain(config.categories)

    comment = _prompt_comment(str(row["comment"] or ""))

    preview = Table(show_header=False, box=None)
    preview.add_row("Transaction datetime", tx_datetime.isoformat(sep="T", timespec="seconds"))
    preview.add_row("Recipient", recipient_name)
    preview.add_row("IBAN", _mask_iban(iban))
    preview.add_row("Amount", format_amount(amount_cents, config.currency))
    preview.add_row("Category", " > ".join(category_chain))
    preview.add_row("Comment", comment or "-")
    preview.add_row("Transaction code", str(row["transaction_code"]))
    console.print(Panel(preview, title=f"Edit Expense #{row['id']}", expand=False))

    save = questionary.confirm("Save changes?", default=True).ask()
    if not save:
        console.print("[yellow]No changes saved.[/yellow]")
        return False

    updated = storage.update_expense(
        expense_id=int(row["id"]),
        transaction_date=tx_datetime.isoformat(sep="T", timespec="seconds"),
        recipient_name=recipient_name,
        iban=iban,
        amount_cents=amount_cents,
        category_chain=category_chain,
        comment=comment,
    )
    if updated:
        console.print("[green]Expense updated.[/green]")
        return True

    console.print("[red]Expense could not be updated (record missing).[/red]")
    return False


def expense_history_flow(config: AppConfig, storage: Storage) -> None:
    """Browse expense history and optionally edit or delete records."""
    back_value = "__back__"

    while True:
        rows = storage.list_expenses()
        if not rows:
            console.print("[yellow]No expenses recorded yet.[/yellow]")
            return

        choices = [
            {"name": _history_choice_label(row), "value": int(row["id"])}
            for row in rows
        ]
        choices.append({"name": "Back", "value": back_value})

        selected_id = questionary.select(
            "Expense history (newest first)",
            choices=choices,
        ).ask()
        if selected_id in (None, back_value):
            return

        selected = next((row for row in rows if int(row["id"]) == selected_id), None)
        if selected is None:
            console.print("[red]Selected record no longer exists.[/red]")
            continue

        _print_history_details(selected)

        action = questionary.select(
            "Choose action",
            choices=[
                {"name": "Back to list", "value": "back"},
                {"name": "Edit record", "value": "edit"},
                {"name": "Delete record", "value": "delete"},
            ],
        ).ask()

        if action in (None, "back"):
            continue

        if action == "edit":
            _edit_expense_flow(config, storage, selected)
            continue

        if action == "delete":
            confirm = questionary.confirm(
                f"Delete expense #{selected['id']}? This cannot be undone.",
                default=False,
            ).ask()
            if confirm:
                deleted = storage.delete_expense(int(selected["id"]))
                if deleted:
                    console.print("[green]Expense deleted.[/green]")
                else:
                    console.print("[red]Expense could not be deleted (record missing).[/red]")
