import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

import budgeteer.cli as cli_module
import budgeteer.interactive_components.prompts as prompts_module
from budgeteer.cli import app
from budgeteer.models import AppConfig
from budgeteer.storage import Storage


runner = CliRunner()


def _build_config(tmp_path: Path, db_name: str = "budgeteer.db") -> AppConfig:
    return AppConfig(
        database_path=str(tmp_path / db_name),
        categories={"Operations": ["Venue"]},
    )


def _patch_load_config(monkeypatch, cfg: AppConfig, calls: dict[str, object]) -> None:
    def fake_load_config(config_path: str | None) -> AppConfig:
        calls["config_path"] = config_path
        return cfg

    monkeypatch.setattr(cli_module, "load_config", fake_load_config)


class PromptResult:
    def __init__(self, value: Any):
        self._value = value

    def ask(self) -> Any:
        return self._value


def _patch_questionary_prompts(
    monkeypatch,
    *,
    text_values: list[str],
    select_values: list[str],
    confirm_value: bool = True,
) -> None:
    text_answers = iter(text_values)
    select_answers = iter(select_values)

    def fake_text(*args: Any, **kwargs: Any) -> PromptResult:
        return PromptResult(next(text_answers))

    def fake_select(*args: Any, **kwargs: Any) -> PromptResult:
        return PromptResult(next(select_answers))

    def fake_confirm(*args: Any, **kwargs: Any) -> PromptResult:
        return PromptResult(confirm_value)

    monkeypatch.setattr(prompts_module.questionary, "text", fake_text)
    monkeypatch.setattr(prompts_module.questionary, "select", fake_select)
    monkeypatch.setattr(prompts_module.questionary, "confirm", fake_confirm)


def test_record_expense_happy_path(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "budgeteer.db"
    cfg = _build_config(tmp_path)

    calls: dict[str, object] = {}
    _patch_load_config(monkeypatch, cfg, calls)

    class DummyStorage:
        def __init__(self, path: Path):
            calls["storage_path"] = path

        def close(self) -> None:
            calls["storage_closed"] = True

    def fake_record_expense_flow(received_cfg: AppConfig, storage: DummyStorage) -> bool:
        calls["flow_called"] = True
        calls["cfg_is_same"] = received_cfg is cfg
        calls["storage_type"] = type(storage)
        return True

    monkeypatch.setattr(cli_module, "Storage", DummyStorage)
    monkeypatch.setattr(cli_module, "record_expense_flow", fake_record_expense_flow)

    result = runner.invoke(app, ["record-expense"])

    assert result.exit_code == 0
    assert calls["config_path"] is None
    assert calls["storage_path"] == db_path
    assert calls["flow_called"] is True
    assert calls["cfg_is_same"] is True
    assert calls["storage_type"] is DummyStorage
    assert calls["storage_closed"] is True


def test_record_expense_happy_path_with_preexisting_recipients(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "budgeteer.db"
    cfg = _build_config(tmp_path)

    seeded_storage = Storage(db_path)
    try:
        seeded_storage.save_expense(
            transaction_date="2026-03-25T12:00:00",
            recipient_name="Existing Club Vendor",
            iban="DE00123456780000000099",
            amount_cents=1050,
            currency="EUR",
            category_chain=["Operations", "Venue"],
            comment="seed",
            transaction_code="EXISTING-01",
        )
    finally:
        seeded_storage.close()

    calls: dict[str, object] = {}
    _patch_load_config(monkeypatch, cfg, calls)

    def fake_record_expense_flow(received_cfg: AppConfig, storage: Storage) -> bool:
        calls["flow_called"] = True
        calls["cfg_is_same"] = received_cfg is cfg
        calls["recipients"] = storage.list_recipient_names()
        return True

    monkeypatch.setattr(cli_module, "record_expense_flow", fake_record_expense_flow)

    result = runner.invoke(app, ["record-expense"])

    assert result.exit_code == 0
    assert calls["config_path"] is None
    assert calls["flow_called"] is True
    assert calls["cfg_is_same"] is True
    assert calls["recipients"] == ["Existing Club Vendor"]


def test_record_expense_command_integration_happy_path(monkeypatch, tmp_path: Path) -> None:
    cfg = _build_config(tmp_path, db_name="fake.db")

    class FakeStorage:
        instance: "FakeStorage | None" = None

        def __init__(self, path: Path):
            self.path = path
            self.saved_payload: dict[str, Any] | None = None
            self.closed = False
            FakeStorage.instance = self

        def list_recipient_names(self) -> list[str]:
            return []

        def get_recipient(self, name: str) -> None:
            return None

        def next_transaction_code(self, base_code: str) -> str:
            return base_code

        def save_expense(self, **kwargs: Any) -> None:
            self.saved_payload = kwargs

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(cli_module, "load_config", lambda _config_path: cfg)
    monkeypatch.setattr(cli_module, "Storage", FakeStorage)
    _patch_questionary_prompts(
        monkeypatch,
        text_values=[
            "2026-03-25T10:11:12",  # transaction datetime
            "Alpha Supplies",  # recipient name
            "DE00123456780000000001",  # iban
            "12.34",  # amount
            "Monthly rental",  # comment
        ],
        select_values=[
            "Operations",  # category
            "Venue",  # subcategory
        ],
    )

    result = runner.invoke(app, ["record-expense"])

    assert result.exit_code == 0
    assert FakeStorage.instance is not None
    assert FakeStorage.instance.saved_payload is not None
    assert FakeStorage.instance.saved_payload["transaction_date"] == "2026-03-25T10:11:12"
    assert FakeStorage.instance.saved_payload["recipient_name"] == "Alpha Supplies"
    assert FakeStorage.instance.saved_payload["iban"] == "DE00123456780000000001"
    assert FakeStorage.instance.saved_payload["amount_cents"] == 1234
    assert FakeStorage.instance.saved_payload["currency"] == "EUR"
    assert FakeStorage.instance.saved_payload["category_chain"] == ["Operations", "Venue"]
    assert FakeStorage.instance.saved_payload["comment"] == "Monthly rental"
    assert FakeStorage.instance.saved_payload["transaction_code"] == "ALPHASUP-OPER-VENU-260325"
    assert FakeStorage.instance.closed is True


def test_prompt_recipient_autocomplete_refreshes_on_backspace(monkeypatch) -> None:
    class FakeStorage:
        def list_recipient_names(self) -> list[str]:
            return ["Alpha Supplies", "Beta Services"]

        def get_recipient(self, name: str) -> None:
            return None

    captured: dict[str, Any] = {}

    class FakeBuffer:
        def start_completion(self, *, select_first: bool) -> None:
            captured["start_completion_select_first"] = select_first

    class FakeApplication:
        def __init__(self) -> None:
            self.current_buffer = FakeBuffer()
            self.pre_run_callables: list[Any] = []

    class FakeQuestion:
        def __init__(self) -> None:
            self.application = FakeApplication()

        def ask(self) -> str:
            for callback in self.application.pre_run_callables:
                callback()
            return "Alpha Supplies"

    def fake_autocomplete(*args: Any, **kwargs: Any) -> FakeQuestion:
        captured["kwargs"] = kwargs
        return FakeQuestion()

    def fake_text(*args: Any, **kwargs: Any) -> PromptResult:
        return PromptResult("DE00123456780000000001")

    monkeypatch.setattr(prompts_module.questionary, "autocomplete", fake_autocomplete)
    monkeypatch.setattr(prompts_module.questionary, "text", fake_text)

    name, iban = prompts_module._prompt_recipient(FakeStorage())

    assert name == "Alpha Supplies"
    assert iban == "DE00123456780000000001"
    assert captured["kwargs"]["complete_while_typing"] is True
    assert captured["kwargs"].get("key_bindings") is not None


def test_prompt_recipient_shows_options_on_start(monkeypatch) -> None:
    class FakeStorage:
        def list_recipient_names(self) -> list[str]:
            return ["Alpha Supplies", "Beta Services"]

        def get_recipient(self, name: str) -> None:
            return None

    class FakeBuffer:
        def __init__(self) -> None:
            self.start_completion_called = False
            self.select_first_value: bool | None = None

        def start_completion(self, *, select_first: bool) -> None:
            self.start_completion_called = True
            self.select_first_value = select_first

    class FakeApplication:
        def __init__(self, buffer: FakeBuffer) -> None:
            self.current_buffer = buffer
            self.pre_run_callables: list[Any] = []

    class FakeQuestion:
        def __init__(self) -> None:
            self.buffer = FakeBuffer()
            self.application = FakeApplication(self.buffer)

        def ask(self) -> str:
            for callback in self.application.pre_run_callables:
                callback()
            return "Alpha Supplies"

    fake_question = FakeQuestion()

    def fake_autocomplete(*args: Any, **kwargs: Any) -> FakeQuestion:
        return fake_question

    def fake_text(*args: Any, **kwargs: Any) -> PromptResult:
        return PromptResult("DE00123456780000000001")

    monkeypatch.setattr(prompts_module.questionary, "autocomplete", fake_autocomplete)
    monkeypatch.setattr(prompts_module.questionary, "text", fake_text)

    name, iban = prompts_module._prompt_recipient(FakeStorage())

    assert name == "Alpha Supplies"
    assert iban == "DE00123456780000000001"
    assert len(fake_question.application.pre_run_callables) == 1
    assert fake_question.buffer.start_completion_called is True
    assert fake_question.buffer.select_first_value is False


def test_export_last_24h_writes_recent_rows_only(monkeypatch, tmp_path: Path) -> None:
    cfg = _build_config(tmp_path)
    calls: dict[str, object] = {}
    _patch_load_config(monkeypatch, cfg, calls)

    storage = Storage(Path(cfg.database_path))
    try:
        storage.save_expense(
            transaction_date="2026-03-24T09:00:00",
            recipient_name="Older Vendor",
            iban="DE00123456780000000011",
            amount_cents=1111,
            currency="EUR",
            category_chain=["Operations", "Venue"],
            comment="older",
            transaction_code="OLDER-01",
        )
        storage.save_expense(
            transaction_date="2026-03-25T09:00:00",
            recipient_name="Recent Vendor",
            iban="DE00123456780000000022",
            amount_cents=2222,
            currency="EUR",
            category_chain=["Operations", "Venue"],
            comment="recent",
            transaction_code="RECENT-01",
        )

        now = datetime.now(UTC)
        old_created = (now - timedelta(hours=25)).isoformat(timespec="seconds")
        recent_created = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        with storage.conn:
            storage.conn.execute(
                "UPDATE expenses SET created_at = ? WHERE transaction_code = ?",
                (old_created, "OLDER-01"),
            )
            storage.conn.execute(
                "UPDATE expenses SET created_at = ? WHERE transaction_code = ?",
                (recent_created, "RECENT-01"),
            )
    finally:
        storage.close()

    output_path = tmp_path / "last24h.csv"
    result = runner.invoke(app, ["export-last-24h", "--output", str(output_path)])

    assert result.exit_code == 0
    assert calls["config_path"] is None
    assert output_path.exists()

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["transaction_code"] == "RECENT-01"
    assert rows[0]["recipient_name"] == "Recent Vendor"
    assert "iban" not in rows[0]
