from __future__ import annotations

from pathlib import Path

import yaml
from platformdirs import user_config_dir

from budgeteer.models import AppConfig

DEFAULT_CONFIG_FILE = "config.yaml"
APP_NAME = "budgeteer"


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / DEFAULT_CONFIG_FILE


def resolve_config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return default_config_path()


def load_config(config_path: str | None) -> AppConfig:
    path = resolve_config_path(config_path)

    if not path.exists():
        message = (
            f"Config not found at {path}. "
            "Copy config.example.yaml into this location and adjust it."
        )
        raise FileNotFoundError(message)

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return AppConfig.model_validate(data)


def ensure_config_directory(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
