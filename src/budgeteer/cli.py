from __future__ import annotations

import csv
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import questionary
import typer
from rich.console import Console

from budgeteer.config import ensure_config_directory, load_config, resolve_config_path
from budgeteer.interactive_components.history import expense_history_flow
from budgeteer.interactive_components.record import record_expense_flow
from budgeteer.models import AppConfig
from budgeteer.storage import Storage

app = typer.Typer(help="Budgeteer expense CLI", no_args_is_help=True)
console = Console()


def _load_runtime_config(config_path: str | None) -> AppConfig:
    """Load runtime config and print setup guidance when missing."""
    try:
        return load_config(config_path)
    except FileNotFoundError as exc:
        resolved_path = resolve_config_path(config_path)
        ensure_config_directory(resolved_path)
        console.print(f"[red]{exc}[/red]")
        console.print(
            "Create a config file first, for example:\n"
            f"  cp config.example.yaml {resolved_path}"
        )
        raise typer.Exit(code=1) from exc


def _run_with_storage(
    config: AppConfig,
    flow: Callable[[AppConfig, Storage], object],
) -> None:
    """Open storage, execute an interactive flow, and close resources safely."""
    db_path = Path(config.database_path).expanduser()

    storage = Storage(db_path)
    try:
        flow(config, storage)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
    finally:
        storage.close()


@app.callback()
def cli() -> None:
    """Budgeteer command group."""


@app.command("record-expense")
def record_expense(
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to runtime YAML config file",
    ),
) -> None:
    """Record an expense through an interactive prompt flow."""
    cfg = _load_runtime_config(config)

    def _record_expense_loop(current_cfg: AppConfig, storage: Storage) -> None:
        while True:
            saved = record_expense_flow(current_cfg, storage)
            if not saved:
                return
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                return

            again = questionary.confirm("Record another expense?", default=False).ask()
            if not again:
                return

    _run_with_storage(cfg, _record_expense_loop)


@app.command("history")
def history(
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to runtime YAML config file",
    ),
) -> None:
    """Browse expense history and edit or delete records."""
    cfg = _load_runtime_config(config)
    _run_with_storage(cfg, expense_history_flow)


@app.command("export-last-24h")
def export_last_24h(
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to runtime YAML config file",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="CSV output path (default: ./budgeteer-last-24h-YYYY-MM-DDTHHMM.csv)",
    ),
) -> None:
    """Export expenses from the last 24 hours to CSV (excluding IBAN)."""
    cfg = _load_runtime_config(config)

    now_local = datetime.now().astimezone()
    start_local = now_local - timedelta(hours=24)
    end_iso = now_local.astimezone(UTC).isoformat(timespec="seconds")
    start_iso = start_local.astimezone(UTC).isoformat(timespec="seconds")

    default_name = now_local.strftime("budgeteer-last-24h-%Y-%m-%dT%H%M.csv")
    output_path = Path(output).expanduser() if output else Path(default_name)

    headers = [
        "id",
        "transaction_date",
        "recipient_name",
        "amount_cents",
        "currency",
        "category_path",
        "comment",
        "transaction_code",
        "created_at",
    ]

    def _export(_cfg: AppConfig, storage: Storage) -> None:
        rows = storage.list_expenses_created_between(start_iso, end_iso)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row[field] for field in headers})

        console.print(
            f"[green]Exported {len(rows)} expense(s) from the last 24h to {output_path}.[/green]"
        )

    _run_with_storage(cfg, _export)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
