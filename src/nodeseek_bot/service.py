from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from .config import Config
from .formatter import format_post
from .matcher import match_post
from .models import utc_now
from .rss_fetcher import FeedError, RssFetcher
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CheckResult:
    fetched: int = 0
    new_posts: int = 0
    users_checked: int = 0
    messages_sent: int = 0
    duration_seconds: float = 0
    error: str | None = None


class MonitorService:
    def __init__(self, config: Config, storage: Storage, fetcher: RssFetcher) -> None:
        self.config = config
        self.storage = storage
        self.fetcher = fetcher
        self.started_at = utc_now()
        self.last_check_at: datetime | None = None
        self.last_result: CheckResult | None = None
        self._lock = asyncio.Lock()

    async def check(self, bot: object) -> CheckResult:
        if self._lock.locked():
            logger.warning("上一轮监控尚未结束，跳过本轮")
            return CheckResult(error="上一轮仍在运行")

        async with self._lock:
            started = monotonic()
            checked_at = utc_now()
            result = CheckResult()
            try:
                posts = await self.fetcher.fetch()
                result.fetched = len(posts)
                result.new_posts = self.storage.save_posts(posts, checked_at)

                if self.storage.get_state("feed_initialized") != "1":
                    self.storage.reset_delivery_window_for_all(checked_at)
                    self.storage.set_state("feed_initialized", "1")
                    logger.info("首次抓取已建立水位线，不推送历史条目")
                    return self._finish(result, started, checked_at)

                for user in self.storage.list_due_users(checked_at):
                    keywords = self.storage.list_keywords(user.user_id, include_excluded=True)
                    if not keywords:
                        self.storage.mark_checked(user.user_id, checked_at)
                        result.users_checked += 1
                        continue

                    had_retryable_error = False
                    for post in self.storage.list_unsent_posts(user):
                        matched = match_post(post, keywords, user.match_scope)
                        if not matched:
                            continue
                        try:
                            await bot.send_message(
                                chat_id=user.user_id,
                                text=format_post(post, matched),
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("查看原帖", url=post.link)]]
                                ),
                            )
                            self.storage.record_sent(user.user_id, post, matched)
                            result.messages_sent += 1
                        except Forbidden:
                            logger.warning("用户 %s 已阻止机器人，自动暂停", user.user_id)
                            self.storage.set_active(user.user_id, False)
                            had_retryable_error = False
                            break
                        except TelegramError as exc:
                            logger.warning(
                                "向用户 %s 推送失败：%s", user.user_id, type(exc).__name__
                            )
                            had_retryable_error = True
                            break
                    if not had_retryable_error:
                        self.storage.mark_checked(user.user_id, checked_at)
                    result.users_checked += 1

                return self._finish(result, started, checked_at)
            except FeedError as exc:
                logger.error("监控任务抓取失败：%s", exc)
                result.error = str(exc)
                return self._finish(result, started, checked_at)
            except Exception:
                logger.exception("监控任务发生未处理异常")
                result.error = "内部错误"
                return self._finish(result, started, checked_at)

    def _finish(self, result: CheckResult, started: float, checked_at: datetime) -> CheckResult:
        result.duration_seconds = monotonic() - started
        self.last_check_at = checked_at
        self.last_result = result
        logger.info(
            "监控任务完成：抓取=%s 新帖=%s 用户=%s 推送=%s 耗时=%.3fs 错误=%s",
            result.fetched,
            result.new_posts,
            result.users_checked,
            result.messages_sent,
            result.duration_seconds,
            result.error,
        )
        return result
