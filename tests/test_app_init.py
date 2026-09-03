"""Tests for project .env loading during application initialization."""

import os
from pathlib import Path

import pytest

from app import _load_project_dotenv
from app.config import AppConfig


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [
        "SECRET_KEY",
        "AGENT_MANAGER_MODEL",
        "AGENT_MANAGER_PROVIDER",
        "DATABASE_URL",
        "AGENT_DESIGNER_MODEL",
        "AGENT_DESIGNER_PROVIDER",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def _write_dotenv(directory: Path) -> Path:
    path = directory / ".env"
    path.write_text(
        "SECRET_KEY=dotenv-secret\n"
        "AGENT_MANAGER_MODEL=dotenv-model\n"
        "AGENT_MANAGER_PROVIDER=dotenv-provider\n"
    )
    return path


def test_load_project_dotenv_populates_missing_env(
    clean_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_dotenv(tmp_path)

    loaded = _load_project_dotenv(path)

    assert loaded is True
    assert os.environ["SECRET_KEY"] == "dotenv-secret"
    assert os.environ["AGENT_MANAGER_MODEL"] == "dotenv-model"
    assert os.environ["AGENT_MANAGER_PROVIDER"] == "dotenv-provider"


def test_load_project_dotenv_does_not_override_existing_env(
    clean_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "shell-secret")
    path = _write_dotenv(tmp_path)

    _load_project_dotenv(path)

    assert os.environ["SECRET_KEY"] == "shell-secret"


def test_load_project_dotenv_returns_false_when_file_missing(
    clean_env: None, tmp_path: Path
) -> None:
    assert _load_project_dotenv(tmp_path / ".env") is False


def test_appconfig_uses_dotenv_values_when_shell_env_empty(
    clean_env: None, tmp_path: Path
) -> None:
    _write_dotenv(tmp_path)
    _load_project_dotenv(tmp_path / ".env")

    config = AppConfig()

    assert config.secret_key == "dotenv-secret"
    assert config.manager_model_config.provider == "dotenv-provider"
    assert config.manager_model_config.model == "dotenv-model"


def test_appconfig_overrides_win_over_dotenv_and_shell(
    clean_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "shell-secret")
    _write_dotenv(tmp_path)
    _load_project_dotenv(tmp_path / ".env")

    config = AppConfig(overrides={"SECRET_KEY": "override-secret"})

    assert config.secret_key == "override-secret"