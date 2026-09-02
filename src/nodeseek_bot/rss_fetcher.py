from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
from datetime import datetime, timezone
from html.parser import HTMLParser
from time import struct_time
from urllib.parse import urlparse

import feedparser
import httpx

from .config import RssConfig
from .models import Post

logger = logging.getLogger(__name__)


class FeedError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        return " ".join("".join(parser.parts).split())
    except Exception:
        return " ".join(value.split())


def _valid_link(value: str) -> str:
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _entry_value(entry: object, key: str, default: object = "") -> object:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _published(value: object) -> datetime | None:
    if isinstance(value, struct_time):
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    if isinstance(value, tuple) and len(value) >= 9:
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


def parse_feed(content: bytes | str) -> list[Post]:
    parsed = feedparser.parse(content)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        raise FeedError(f"RSS 无法解析：{type(parsed.bozo_exception).__name__}")

    posts: list[Post] = []
    for entry in parsed.entries:
        title = html_to_text(str(_entry_value(entry, "title", ""))).strip()
        link = _valid_link(str(_entry_value(entry, "link", "")).strip())
        if not title or not link:
            logger.warning("跳过缺少标题或有效链接的 RSS 条目")
            continue

        raw_id = str(
            _entry_value(entry, "id", "") or _entry_value(entry, "guid", "") or link
        ).strip()
        post_id = raw_id or hashlib.sha256(f"{link}\0{title}".encode()).hexdigest()
        author = html_to_text(str(_entry_value(entry, "author", "未知"))).strip() or "未知"
        summary_value = _entry_value(entry, "summary", "") or _entry_value(entry, "description", "")
        summary = html_to_text(str(summary_value))

        tags = _entry_value(entry, "tags", [])
        categories: list[str] = []
        if isinstance(tags, list):
            for tag in tags:
                term = _entry_value(tag, "term", "")
                if term:
                    categories.append(html_to_text(str(term)))
        category = " / ".join(dict.fromkeys(categories)) or "未分类"
        published = _published(
            _entry_value(entry, "published_parsed", None)
            or _entry_value(entry, "updated_parsed", None)
        )
        posts.append(
            Post(
                post_id=post_id,
                title=title,
                link=link,
                author=author,
                category=category,
                published_at=published,
                summary=summary,
            )
        )
    return posts


class RssFetcher:
    def __init__(self, config: RssConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": config.user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
            },
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch(self) -> list[Post]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_times + 1):
            try:
                response = await self.client.get(self.config.url)
                response.raise_for_status()
                posts = parse_feed(response.content)
                logger.info("RSS 抓取成功", extra={"post_count": len(posts)})
                return posts
            except (httpx.HTTPError, FeedError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                logger.warning(
                    "RSS 抓取失败（第 %s/%s 次）：%s",
                    attempt,
                    self.config.retry_times,
                    type(exc).__name__,
                )
                if not retryable or attempt == self.config.retry_times:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 30))
        raise FeedError("RSS 抓取失败") from last_error
