import sqlite3
from datetime import timedelta
from pathlib import Path

from nodeseek_bot.models import Post, utc_now
from nodeseek_bot.storage import Storage


def make_storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    return storage


def test_users_keywords_and_isolation(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    storage.ensure_user(1, "alice")
    storage.ensure_user(2, "bob")
    assert storage.add_keyword(1, "VPS")
    assert not storage.add_keyword(1, "vps")
    assert [item.keyword for item in storage.list_keywords(1)] == ["VPS"]
    assert storage.list_keywords(2) == []
    assert not storage.remove_keyword(2, "VPS")


def test_group_chat_is_stored_as_independent_subscriber(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    group = storage.ensure_user(
        -1001234567890,
        "market_group",
        chat_type="supergroup",
        chat_title="机器交易群",
    )
    storage.ensure_user(1, "alice")
    assert group.chat_type == "supergroup"
    assert group.chat_title == "机器交易群"
    assert storage.add_keyword(group.user_id, "香港")
    assert storage.list_keywords(1) == []


def test_existing_private_subscriber_schema_is_migrated(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_active INTEGER NOT NULL,
                check_interval INTEGER NOT NULL,
                match_scope TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                delivery_since TEXT NOT NULL,
                last_checked_at TEXT,
                dmit_stock_enabled INTEGER NOT NULL DEFAULT 0,
                dmit_enabled_since TEXT,
                bwh_stock_enabled INTEGER NOT NULL DEFAULT 0,
                bwh_enabled_since TEXT
            );
            INSERT INTO users (
                user_id, username, is_active, check_interval, match_scope,
                created_at, updated_at, delivery_since
            ) VALUES (
                1, 'alice', 1, 5, 'title',
                '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00'
            );
            """
        )

    storage = Storage(database)
    storage.initialize()
    subscriber = storage.get_user(1)
    assert subscriber
    assert subscriber.chat_type == "private"
    assert subscriber.chat_title is None


def test_post_deduplication_and_delivery_window(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    user = storage.ensure_user(1, "alice")
    post = Post("1", "VPS 优惠", "https://example.com/1")
    discovered = utc_now() + timedelta(seconds=1)
    assert storage.save_posts([post], discovered) == 1
    assert storage.save_posts([post], discovered) == 0
    assert storage.list_unsent_posts(user) == [post]
    assert storage.record_sent(1, post, ["VPS"])
    assert not storage.record_sent(1, post, ["VPS"])
    assert storage.list_unsent_posts(user) == []


def test_resume_starts_a_new_delivery_window(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    storage.ensure_user(1, "alice")
    storage.set_active(1, False)
    storage.set_active(1, True)
    user = storage.get_user(1)
    assert user and user.is_active and user.last_checked_at is None
