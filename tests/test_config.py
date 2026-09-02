from pathlib import Path

import pytest

from nodeseek_bot.config import ConfigError, load_config


def test_token_is_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(tmp_path / "missing.yaml")


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    config = load_config(tmp_path / "missing.yaml")
    assert config.telegram.token == "test-token"
    assert config.database.path == tmp_path / "test.db"
    assert config.rss.poll_interval_seconds == 60
