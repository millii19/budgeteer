from __future__ import annotations

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from budgeteer.codegen import build_base_transaction_code
from budgeteer.interactive_components.prompts import (
    _mask_iban,
    _prompt_amount_cents,
    _prompt_comment,
    _prompt_datetime,
    _prompt_recipient,
    _select_category_chain,
)
from budgeteer.models import AppConfig, ExpenseInput
from budgeteer.parsing import format_amount
from budgeteer.storage import Storage

console = Console()


def record_expense_flow(config: AppConfig, storage: Storage) -> bool:
    """Collect expense input interactively, preview it, and persist on confirmation."""
    tx_datetime = _prompt_datetime()
    recipient_name, iban = _prompt_recipient(storage)
    amount_cents = _prompt_amount_cents(config.currency)
    category_chain = _select_category_chain(config.categories)
    comment = _prompt_comment()

    payload = ExpenseInput(
        transaction_date=tx_datetime,
        recipient_name=recipient_name,
        iban=iban,
        amount_cents=amount_cents,
        category_chain=category_chain,
        comment=comment,
    )

    base_code = build_base_transaction_code(
        payload.recipient_name,
        payload.category_chain,
        payload.transaction_date.date(),
    )
    transaction_code = storage.next_transaction_code(base_code)

    table = Table(show_header=False, box=None)
    table.add_row(
        "Transaction datetime",
        payload.transaction_date.isoformat(sep="T", timespec="seconds"),
    )
    table.add_row("Recipient", payload.recipient_name)
    table.add_row("IBAN", _mask_iban(payload.iban))
    table.add_row("Amount", format_amount(payload.amount_cents, config.currency))
    table.add_row("Category", " > ".join(payload.category_chain))
    table.add_row("Comment", payload.comment or "-")
    table.add_row("Transaction code", transaction_code)

    console.print(Panel(table, title="Expense Summary", expand=False))

    save = questionary.confirm("Save this expense?", default=True).ask()
    if not save:
        console.print("[yellow]Nothing saved.[/yellow]")
        return False

    storage.save_expense(
        transaction_date=payload.transaction_date.isoformat(sep="T", timespec="seconds"),
        recipient_name=payload.recipient_name,
        iban=payload.iban,
        amount_cents=payload.amount_cents,
        currency=config.currency,
        category_chain=payload.category_chain,
        comment=payload.comment,
        transaction_code=transaction_code,
    )

    success_text = f"Saved. Transaction code: [bold]{transaction_code}[/bold]"
    console.print(Panel.fit(success_text, style="green"))
    return True
