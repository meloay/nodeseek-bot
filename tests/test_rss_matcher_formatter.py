from datetime import datetime, timezone
from pathlib import Path

from nodeseek_bot.formatter import display_category, format_post, highlight_title
from nodeseek_bot.matcher import match_post
from nodeseek_bot.models import Keyword, Post
from nodeseek_bot.rss_fetcher import parse_feed


def keyword(value: str, keyword_id: int = 1) -> Keyword:
    return Keyword(keyword_id, 1, value, "fuzzy", False, datetime.now(timezone.utc))


def test_parse_feed_fixture() -> None:
    content = Path("tests/fixtures/sample.xml").read_bytes()
    posts = parse_feed(content)
    assert len(posts) == 2
    assert posts[0].post_id == "post-1001"
    assert posts[0].title == "香港 VPS & 流量优惠"
    assert posts[0].category == "情报"
    assert posts[0].summary.startswith("本月套餐")
    assert posts[0].published_at == datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_match_is_case_insensitive_and_returns_all_hits() -> None:
    post = Post("1", "香港 VPS 流量优惠", "https://example.com")
    matched = match_post(post, [keyword("vps"), keyword("优惠", 2)])
    assert matched == ["vps", "优惠"]


def test_title_scope_does_not_match_summary() -> None:
    post = Post("1", "普通标题", "https://example.com", summary="正文含 VPS")
    assert match_post(post, [keyword("VPS")], "title") == []
    assert match_post(post, [keyword("VPS")], "full") == ["VPS"]


def test_html_is_escaped_before_highlighting() -> None:
    rendered = highlight_title("<VPS> & 优惠", ["vps"])
    assert rendered == "&lt;<b>VPS</b>&gt; &amp; 优惠"
    message = format_post(
        Post(
            "1",
            "<VPS>",
            "https://example.com",
            published_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        ),
        ["VPS"],
    )
    assert "&lt;<b>VPS</b>&gt;" in message
    assert "2026-08-28 08:00 UTC+8" in message


def test_category_slugs_are_displayed_in_chinese() -> None:
    expected = {
        "daily": "日常",
        "tech": "技术",
        "info": "情报",
        "review": "测评",
        "trade": "交易",
        "carpool": "拼车",
        "promotion": "推广",
        "promo": "推广",
    }
    for slug, chinese_name in expected.items():
        assert display_category(slug) == chinese_name
    assert display_category("unknown") == "unknown"
    assert display_category("trade / promo") == "交易 / 推广"


def test_formatted_message_uses_chinese_category() -> None:
    message = format_post(Post("1", "VPS", "https://example.com", category="trade"), ["VPS"])
    assert "📂 板块：交易" in message
