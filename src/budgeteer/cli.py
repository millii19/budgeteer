from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from budgeteer.config import ensure_config_directory, load_config, resolve_config_path
from budgeteer.interactive import expense_history_flow, record_expense_flow
from budgeteer.storage import Storage

app = typer.Typer(help="Budgeteer expense CLI", no_args_is_help=True)
console = Console()


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
    try:
        cfg = load_config(config)
    except FileNotFoundError as exc:
        config_path = resolve_config_path(config)
        ensure_config_directory(config_path)
        console.print(f"[red]{exc}[/red]")
        console.print(
            "Create a config file first, for example:\n"
            f"  cp config.example.yaml {config_path}"
        )
        raise typer.Exit(code=1) from exc

    db_path = Path(cfg.database_path).expanduser()

    storage = Storage(db_path)
    try:
        record_expense_flow(cfg, storage)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
    finally:
        storage.close()


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
    try:
        cfg = load_config(config)
    except FileNotFoundError as exc:
        config_path = resolve_config_path(config)
        ensure_config_directory(config_path)
        console.print(f"[red]{exc}[/red]")
        console.print(
            "Create a config file first, for example:\n"
            f"  cp config.example.yaml {config_path}"
        )
        raise typer.Exit(code=1) from exc

    db_path = Path(cfg.database_path).expanduser()

    storage = Storage(db_path)
    try:
        expense_history_flow(cfg, storage)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
    finally:
        storage.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
