from __future__ import annotations

from datetime import UTC, datetime
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


def _prompt_datetime(default_value: str | None = None) -> datetime:
    default_input = default_value or datetime.now(UTC).replace(microsecond=0).isoformat()
    while True:
        raw = questionary.text(
            "Transaction datetime (YYYY-MM-DDTHH:MM:SS, timezone optional)",
            default=default_input,
        ).ask()

        if raw is None:
            raise KeyboardInterrupt

        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(UTC).replace(tzinfo=None)
        except ValueError:
            console.print("[red]Please use ISO datetime format (YYYY-MM-DDTHH:MM:SS).[/red]")


def _prompt_recipient(
    storage: Storage,
    default_name: str | None = None,
    default_iban: str | None = None,
) -> tuple[str, str]:
    names = storage.list_recipient_names()

    while True:
        if names:
            name = questionary.autocomplete(
                "Recipient name",
                choices=names,
                ignore_case=True,
                match_middle=True,
                default=default_name or "",
            ).ask()
        else:
            name = questionary.text("Recipient name", default=default_name or "").ask()

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
    elif default_name and default_iban and default_name.lower() == name.lower():
        keep_current = questionary.confirm(
            f"Keep current IBAN {_mask_iban(default_iban)}?",
            default=True,
        ).ask()
        if keep_current:
            return name, default_iban

    while True:
        iban = questionary.text("IBAN", default=default_iban or "").ask()
        if iban is None:
            raise KeyboardInterrupt
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


def _prompt_amount_cents(currency: str, default_value: str | None = None) -> int:
    while True:
        raw = questionary.text(f"Amount ({currency})", default=default_value or "").ask()
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


def _prompt_comment(default_value: str = "") -> str:
    raw = questionary.text("Comment (optional)", default=default_value).ask()
    if raw is None:
        raise KeyboardInterrupt
    return raw.strip()


def _parse_category_path(path: str) -> list[str]:
    return [part.strip() for part in path.split(">") if part.strip()]


def _amount_input_from_cents(amount_cents: int) -> str:
    return f"{amount_cents / 100:.2f}"


def _history_choice_label(row: Any) -> str:
    return (
        f"#{row['id']} | {row['transaction_date']} | {row['recipient_name']} | "
        f"{format_amount(int(row['amount_cents']), str(row['currency']))} | {row['category_path']}"
    )


def _print_history_details(row: Any) -> None:
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


def record_expense_flow(config: AppConfig, storage: Storage) -> bool:
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
