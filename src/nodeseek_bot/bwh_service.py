from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from time import monotonic

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from .bwh_fetcher import BwhFetcher, BwhFetchError
from .models import UTC_PLUS_8, BwhStockEvent, utc_now
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BwhCheckResult:
    products: int = 0
    available: int = 0
    events_created: int = 0
    messages_sent: int = 0
    duration_seconds: float = 0
    error: str | None = None


def format_bwh_event(event: BwhStockEvent) -> str:
    checked_at = event.created_at.astimezone(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S UTC+8")
    tiers = "、".join(event.tiers) or "未分类"
    specs = " · ".join(event.specs)
    shown_datacenters = list(event.datacenters[:4])
    if len(event.datacenters) > 4:
        shown_datacenters.append(f"另有 {len(event.datacenters) - 4} 个机房")
    datacenters = "；".join(shown_datacenters) or "以购买页为准"
    return "\n".join(
        [
            "🎉 <b>BandwagonHost 套餐补货</b>",
            "",
            f"📦 套餐：<b>{html.escape(event.name)}</b>",
            f"🏷 系列：{html.escape(tiers)}",
            f"📍 机房：{html.escape(datacenters)}",
            f"🖥 配置：{html.escape(specs)}",
            f"💵 价格：{html.escape(event.price)}",
            f"🕒 检测时间：{checked_at}",
        ]
    )


class BwhMonitorService:
    def __init__(self, storage: Storage, fetcher: BwhFetcher) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.last_check_at = None
        self.last_result: BwhCheckResult | None = None
        self._lock = asyncio.Lock()

    async def check(self, bot: object) -> BwhCheckResult:
        if self._lock.locked():
            return BwhCheckResult(error="上一轮仍在运行")

        async with self._lock:
            started = monotonic()
            checked_at = utc_now()
            result = BwhCheckResult()
            try:
                products = await self.fetcher.fetch()
                result.products = len(products)
                result.available = sum(product.is_available for product in products)
                result.events_created = self.storage.sync_bwh_products(products, checked_at)

                for user in self.storage.list_bwh_subscribers():
                    for event in self.storage.list_unsent_bwh_events(user):
                        try:
                            await bot.send_message(
                                chat_id=user.user_id,
                                text=format_bwh_event(event),
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("立即购买", url=event.order_url)]]
                                ),
                            )
                            self.storage.record_bwh_notification(user.user_id, event.id)
                            result.messages_sent += 1
                        except Forbidden:
                            logger.warning("用户 %s 已阻止机器人，自动暂停", user.user_id)
                            self.storage.set_active(user.user_id, False)
                            break
                        except TelegramError as exc:
                            logger.warning(
                                "向用户 %s 推送 BandwagonHost 补货失败：%s",
                                user.user_id,
                                type(exc).__name__,
                            )
                            break
            except BwhFetchError as exc:
                result.error = str(exc)
                logger.error("BandwagonHost 库存任务失败：%s", exc)
            except Exception:
                result.error = "内部错误"
                logger.exception("BandwagonHost 库存任务发生未处理异常")

            result.duration_seconds = monotonic() - started
            self.last_check_at = checked_at
            self.last_result = result
            logger.info(
                "BandwagonHost 库存任务完成：套餐=%s 可购买=%s 补货=%s 推送=%s 耗时=%.3fs 错误=%s",
                result.products,
                result.available,
                result.events_created,
                result.messages_sent,
                result.duration_seconds,
                result.error,
            )
            return result
