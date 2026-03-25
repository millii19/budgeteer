from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import questionary
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console

from budgeteer.category_selector import select_category_chain, select_category_chain_legacy
from budgeteer.parsing import parse_amount_to_cents
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


def _mask_iban(iban: str) -> str:
    """Return a short masked representation of an IBAN for confirmations."""
    compact = iban.replace(" ", "")
    if len(compact) <= 8:
        return compact
    return f"{compact[:4]}...{compact[-4:]}"


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
    return select_category_chain_legacy(categories, questionary.select)


def _select_category_chain(categories: dict[str, Any]) -> list[str]:
    """Select category path with a richer TTY navigator and legacy fallback."""
    return select_category_chain(categories, questionary.select)


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
