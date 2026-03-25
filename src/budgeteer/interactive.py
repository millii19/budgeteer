from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from budgeteer.codegen import build_base_transaction_code
from budgeteer.models import AppConfig, ExpenseInput
from budgeteer.parsing import format_amount, parse_amount_to_cents
from budgeteer.storage import Storage

console = Console()


def _recipient_autocomplete_key_bindings() -> KeyBindings:
    """Build key bindings that keep recipient autocomplete suggestions in sync."""
    kb = KeyBindings()

    @kb.add("backspace")
    @kb.add("c-h")
    def _backspace(event: Any) -> None:
        """Delete one character to the left and refresh completion options."""
        buffer = event.current_buffer
        if buffer.document.cursor_position > 0:
            buffer.delete_before_cursor(count=1)
        buffer.start_completion(select_first=False)

    @kb.add("delete")
    def _delete(event: Any) -> None:
        """Delete one character to the right and refresh completion options."""
        buffer = event.current_buffer
        if buffer.document.cursor_position < len(buffer.text):
            buffer.delete(count=1)
        buffer.start_completion(select_first=False)

    return kb


def _prompt_datetime(default_value: str | None = None) -> datetime:
    """Prompt for an ISO datetime and normalize timezone-aware inputs to naive UTC."""
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
    """Prompt for recipient and IBAN, reusing known recipients when possible."""
    names = storage.list_recipient_names()

    while True:
        if names:
            recipient_prompt = questionary.autocomplete(
                "Recipient name",
                choices=names,
                ignore_case=True,
                match_middle=True,
                complete_while_typing=True,
                key_bindings=_recipient_autocomplete_key_bindings(),
                default=default_name or "",
            )
            recipient_prompt.application.pre_run_callables.append(
                lambda: recipient_prompt.application.current_buffer.start_completion(
                    select_first=False
                )
            )
            name = recipient_prompt.ask()
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
    """Return a short masked representation of an IBAN for confirmations."""
    compact = iban.replace(" ", "")
    if len(compact) <= 8:
        return compact
    return f"{compact[:4]}...{compact[-4:]}"


def _prompt_amount_cents(currency: str, default_value: str | None = None) -> int:
    """Prompt for a monetary value and return the normalized amount in cents."""
    while True:
        raw = questionary.text(f"Amount ({currency})", default=default_value or "").ask()
        if raw is None:
            raise KeyboardInterrupt

        try:
            return parse_amount_to_cents(raw)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")


def _select_category_chain_legacy(categories: dict[str, Any]) -> list[str]:
    """Select category path via sequential questionary selects."""
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


def _select_category_chain(categories: dict[str, Any]) -> list[str]:
    """Select category path with a richer TTY navigator and legacy fallback."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _select_category_chain_legacy(categories)

    locked_chain: list[str] = []
    indices: list[int] = [0]

    def current_node() -> Any:
        """Return the node referenced by the currently locked category segments."""
        cursor: Any = categories
        for segment in locked_chain:
            if not isinstance(cursor, dict) or segment not in cursor:
                return None
            cursor = cursor[segment]
        return cursor

    def options_for_node(node: Any) -> list[str]:
        """Return selectable option labels for a node."""
        if isinstance(node, dict):
            return sorted(node.keys())
        if isinstance(node, list):
            return [str(item) for item in node]
        return []

    def current_options() -> list[str]:
        """Return options for the current cursor position."""
        return options_for_node(current_node())

    def normalize_index() -> None:
        """Ensure the active index exists and stays within current option bounds."""
        depth = len(locked_chain)
        while len(indices) <= depth:
            indices.append(0)
        options = current_options()
        if not options:
            indices[depth] = 0
            return
        indices[depth] = min(max(indices[depth], 0), len(options) - 1)

    def selected_option() -> str | None:
        """Return the currently highlighted option at the active depth."""
        normalize_index()
        options = current_options()
        if not options:
            return None
        return options[indices[len(locked_chain)]]

    def preview_options() -> list[str]:
        """Return child option labels for the current highlighted option."""
        node = current_node()
        choice = selected_option()
        if choice is None:
            return []

        if isinstance(node, dict):
            child = node.get(choice)
            return options_for_node(child)
        return []

    def preview_items() -> list[tuple[str, bool]]:
        """Return preview rows as (label, has_children) tuples."""
        node = current_node()
        choice = selected_option()
        if choice is None or not isinstance(node, dict):
            return []

        child = node.get(choice)
        if isinstance(child, dict):
            return [
                (name, len(options_for_node(child.get(name))) > 0)
                for name in sorted(child.keys())
            ]
        if isinstance(child, list):
            return [(str(item), False) for item in child]
        return []

    def is_leaf_choice(choice: str) -> bool:
        """Check whether a highlighted option resolves to a terminal selection."""
        node = current_node()
        if isinstance(node, dict):
            child = node.get(choice)
            return len(options_for_node(child)) == 0
        if isinstance(node, list):
            return True
        return True

    def at_end_of_path() -> bool:
        """Return True when locked segments point to the final list level."""
        return isinstance(current_node(), list)

    def move(delta: int) -> None:
        """Move active selection up/down with wraparound."""
        normalize_index()
        options = current_options()
        if not options:
            return
        depth = len(locked_chain)
        indices[depth] = (indices[depth] + delta) % len(options)

    def drill() -> None:
        """Move one level deeper into highlighted option if child options exist."""
        choice = selected_option()
        if choice is None:
            return

        node = current_node()
        if isinstance(node, dict):
            child = node.get(choice)
            child_options = options_for_node(child)
            if child_options:
                locked_chain.append(choice)
                normalize_index()
                return

    def confirm_if_leaf() -> list[str] | None:
        """Return a complete category chain if current state is saveable."""
        choice = selected_option()
        if choice is None:
            return None
        # Only selections from the terminal level (right-most path position) can be saved.
        if at_end_of_path() and is_leaf_choice(choice):
            return [*locked_chain, choice]

        return None

    def go_back() -> None:
        """Move one level up and normalize selection indexes."""
        if not locked_chain:
            return
        locked_chain.pop()
        del indices[len(locked_chain) + 1 :]
        normalize_index()

    def breadcrumb_text() -> list[tuple[str, str]]:
        """Render breadcrumb text for current path and highlighted option."""
        selected = selected_option()
        parts = [*locked_chain]
        if selected is not None:
            parts.append(selected)
        if not parts:
            suffix = "  [END]" if at_end_of_path() else ""
            return [("class:muted", f"Path: (root){suffix}")]

        chain = " > ".join(parts)
        if at_end_of_path():
            return [("class:muted", "Path: "), ("", chain), ("class:end", "  [END]")]
        return [("class:muted", "Path: "), ("", chain)]

    def current_text() -> list[tuple[str, str]]:
        """Render the current column with active item highlighting."""
        normalize_index()
        options = current_options()
        if not options:
            return [("class:muted", "(no options)\n")]

        depth = len(locked_chain)
        active = indices[depth]
        lines: list[tuple[str, str]] = []
        for idx, option in enumerate(options):
            prefix = "> " if idx == active else "  "
            style = "class:active" if idx == active else ""
            lines.append((style, f"{prefix}{option}\n"))
        return lines

    def preview_text() -> list[tuple[str, str]]:
        """Render the right-side preview aligned with the active row."""
        depth = len(locked_chain)
        active = indices[depth]
        padding: list[tuple[str, str]] = [("", "\n")] * active

        if at_end_of_path():
            return [
                *padding,
                ("class:end", "End of path reached. Press Enter to save.\n"),
            ]

        items = preview_items()
        if not items:
            return [*padding, ("class:muted", "(no subcategories)\n")]
        return padding + [
            ("class:preview", f"{name}{'...' if has_children else ''}\n")
            for name, has_children in items
        ]

    help_text = "Arrows navigate | Right moves deeper | Enter saves only at [END]"

    center = Window(
        FormattedTextControl(current_text),
        always_hide_cursor=True,
        dont_extend_width=True,
    )
    right = Window(FormattedTextControl(preview_text), always_hide_cursor=True)

    root = HSplit(
        [
            Window(height=1, content=FormattedTextControl(lambda: [("class:muted", help_text)])),
            Window(height=1, content=FormattedTextControl(breadcrumb_text)),
            VSplit(
                [
                    center,
                    Window(width=1, char=" "),
                    right,
                ]
            ),
        ]
    )

    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        """Move selection up one row."""
        move(-1)
        event.app.invalidate()

    @kb.add("down")
    def _down(event: Any) -> None:
        """Move selection down one row."""
        move(1)
        event.app.invalidate()

    @kb.add("left")
    def _left(event: Any) -> None:
        """Go back one level in the category hierarchy."""
        go_back()
        event.app.invalidate()

    @kb.add("right")
    def _right(event: Any) -> None:
        """Drill into the currently highlighted category branch."""
        drill()
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event: Any) -> None:
        """Save selection when positioned at a terminal category path."""
        result = confirm_if_leaf()
        if result is None:
            event.app.invalidate()
            return
        event.app.exit(result=result)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event: Any) -> None:
        """Cancel category selection and return control to caller."""
        event.app.exit(result=None)

    style = Style.from_dict(
        {
            "active": "bold fg:#00afff",
            "muted": "fg:#888888",
            "preview": "fg:#666666",
            "end": "bold fg:#00af5f",
        }
    )

    normalize_index()
    app = Application(
        layout=Layout(root, focused_element=center),
        key_bindings=kb,
        full_screen=False,
        style=style,
    )
    result = app.run()
    if result is None:
        raise KeyboardInterrupt
    return result


def _prompt_comment(default_value: str = "") -> str:
    """Prompt for an optional free-text comment."""
    raw = questionary.text("Comment (optional)", default=default_value).ask()
    if raw is None:
        raise KeyboardInterrupt
    return raw.strip()


def _parse_category_path(path: str) -> list[str]:
    """Parse a persisted category path string into individual path segments."""
    return [part.strip() for part in path.split(">") if part.strip()]


def _amount_input_from_cents(amount_cents: int) -> str:
    """Format integer cents as decimal amount text for prompt defaults."""
    return f"{amount_cents / 100:.2f}"


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
