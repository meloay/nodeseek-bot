from datetime import timedelta
from pathlib import Path

import pytest

from nodeseek_bot.config import (
    BwhConfig,
    Config,
    DatabaseConfig,
    DmitConfig,
    LoggingConfig,
    RssConfig,
    TelegramConfig,
    UserDefaults,
)
from nodeseek_bot.models import Post, utc_now
from nodeseek_bot.service import MonitorService
from nodeseek_bot.storage import Storage


class FakeFetcher:
    def __init__(self, batches: list[list[Post]]) -> None:
        self.batches = batches

    async def fetch(self) -> list[Post]:
        return self.batches.pop(0)


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("subscriber_id", [123, -1001234567890])
async def test_first_fetch_is_baseline_then_new_match_is_sent(
    tmp_path: Path, subscriber_id: int
) -> None:
    config = Config(
        TelegramConfig("test"),
        RssConfig(),
        DmitConfig(),
        BwhConfig(),
        UserDefaults(default_interval_minutes=1),
        DatabaseConfig(tmp_path / "test.db"),
        LoggingConfig(file=tmp_path / "test.log"),
    )
    storage = Storage(config.database.path, default_interval=1)
    storage.initialize()
    chat_type = "supergroup" if subscriber_id < 0 else "private"
    storage.ensure_user(subscriber_id, "alice", chat_type=chat_type)
    storage.add_keyword(subscriber_id, "VPS")
    old = Post("old", "旧 VPS 帖子", "https://example.com/old")
    new = Post("new", "新 VPS 优惠", "https://example.com/new")
    fetcher = FakeFetcher([[old], [old, new]])
    service = MonitorService(config, storage, fetcher)  # type: ignore[arg-type]
    bot = FakeBot()

    first = await service.check(bot)
    assert first.messages_sent == 0
    storage.mark_checked(subscriber_id, utc_now() - timedelta(minutes=2))
    second = await service.check(bot)
    assert second.messages_sent == 1
    assert bot.messages[0]["chat_id"] == subscriber_id
