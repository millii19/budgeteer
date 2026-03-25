from __future__ import annotations

from datetime import date
from typing import Any

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from budgeteer.codegen import build_base_transaction_code
from budgeteer.models import AppConfig, ExpenseInput
from budgeteer.parsing import format_amount, parse_amount_to_cents
from budgeteer.storage import Storage

console = Console()


def _prompt_date() -> date:
    while True:
        raw = questionary.text(
            "Transaction date (YYYY-MM-DD)",
            default=str(date.today()),
        ).ask()

        if raw is None:
            raise KeyboardInterrupt

        try:
            return date.fromisoformat(raw)
        except ValueError:
            console.print("[red]Please use YYYY-MM-DD.[/red]")


def _prompt_recipient(storage: Storage) -> tuple[str, str]:
    names = storage.list_recipient_names()

    while True:
        if names:
            name = questionary.autocomplete(
                "Recipient name",
                choices=names,
                ignore_case=True,
                match_middle=True,
            ).ask()
        else:
            name = questionary.text("Recipient name").ask()

        if name is None:
            raise KeyboardInterrupt

        if name.strip():
            break

        console.print("[red]Recipient name is required.[/red]")

    name = name.strip()

    recipient = storage.get_recipient(name)
    if recipient:
        masked = _mask_iban(str(recipient["iban"]))
        keep = questionary.confirm(
            f"Use stored IBAN {masked}?",
            default=True,
        ).ask()
        if keep:
            return name, str(recipient["iban"])

    while True:
        iban = questionary.text("IBAN").ask()
        if not iban:
            console.print("[red]IBAN is required.[/red]")
            continue
        compact = iban.replace(" ", "").upper()
        if len(compact) < 12:
            console.print("[red]IBAN looks too short.[/red]")
            continue
        return name, compact


def _mask_iban(iban: str) -> str:
    compact = iban.replace(" ", "")
    if len(compact) <= 8:
        return compact
    return f"{compact[:4]}...{compact[-4:]}"


def _prompt_amount_cents(currency: str) -> int:
    while True:
        raw = questionary.text(f"Amount ({currency})").ask()
        if raw is None:
            raise KeyboardInterrupt

        try:
            return parse_amount_to_cents(raw)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")


def _select_category_chain(categories: dict[str, Any]) -> list[str]:
    chain: list[str] = []
    cursor: Any = categories

    while isinstance(cursor, dict):
        options = sorted(cursor.keys())
        choice = questionary.select("Select category", choices=options).ask()
        if choice is None:
            raise KeyboardInterrupt
        chain.append(choice)
        cursor = cursor[choice]

    if isinstance(cursor, list) and cursor:
        choice = questionary.select("Select subcategory", choices=cursor).ask()
        if choice is None:
            raise KeyboardInterrupt
        chain.append(choice)

    return chain


def _prompt_comment() -> str:
    raw = questionary.text("Comment (optional)", default="").ask()
    if raw is None:
        raise KeyboardInterrupt
    return raw.strip()


def record_expense_flow(config: AppConfig, storage: Storage) -> bool:
    tx_date = _prompt_date()
    recipient_name, iban = _prompt_recipient(storage)
    amount_cents = _prompt_amount_cents(config.currency)
    category_chain = _select_category_chain(config.categories)
    comment = _prompt_comment()

    payload = ExpenseInput(
        transaction_date=tx_date,
        recipient_name=recipient_name,
        iban=iban,
        amount_cents=amount_cents,
        category_chain=category_chain,
        comment=comment,
    )

    base_code = build_base_transaction_code(
        payload.recipient_name,
        payload.category_chain,
        payload.transaction_date,
    )
    transaction_code = storage.next_transaction_code(base_code)

    table = Table(show_header=False, box=None)
    table.add_row("Date", str(payload.transaction_date))
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
        transaction_date=str(payload.transaction_date),
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
