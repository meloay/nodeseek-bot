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
