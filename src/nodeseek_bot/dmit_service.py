from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from time import monotonic

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from .dmit_fetcher import DmitFetcher, DmitFetchError
from .models import UTC_PLUS_8, DmitStockEvent, utc_now
from .storage import Storage

logger = logging.getLogger(__name__)

LOCATION_NAMES = {"lax": "洛杉矶", "hkg": "香港", "tyo": "东京"}
NETWORK_NAMES = {
    "premium": "Premium 优质网络",
    "eyeball": "Eyeball 优化网络",
    "tier1": "Tier 1 网络",
    "t1": "Tier 1 网络",
}


@dataclass(slots=True)
class DmitCheckResult:
    products: int = 0
    available: int = 0
    events_created: int = 0
    messages_sent: int = 0
    duration_seconds: float = 0
    error: str | None = None


def format_dmit_event(event: DmitStockEvent) -> str:
    location = LOCATION_NAMES.get(event.location.casefold(), event.location.upper())
    network = NETWORK_NAMES.get(event.network.casefold(), event.network)
    product_code = ".".join(
        [event.location.upper(), event.hardware.upper(), event.network.upper(), event.name]
    )
    specs = " · ".join(event.specs)
    checked_at = event.created_at.astimezone(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S UTC+8")
    return "\n".join(
        [
            "🎉 <b>DMIT 套餐补货</b>",
            "",
            f"📦 套餐：<b>{html.escape(product_code)}</b>",
            f"📍 地区：{html.escape(location)}",
            f"🌐 网络：{html.escape(network)}",
            f"🖥 配置：{html.escape(specs)}",
            f"💵 价格：{html.escape(event.price)}",
            f"🕒 检测时间：{checked_at}",
        ]
    )


class DmitMonitorService:
    def __init__(self, storage: Storage, fetcher: DmitFetcher) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.last_check_at = None
        self.last_result: DmitCheckResult | None = None
        self._lock = asyncio.Lock()

    async def check(self, bot: object) -> DmitCheckResult:
        if self._lock.locked():
            return DmitCheckResult(error="上一轮仍在运行")

        async with self._lock:
            started = monotonic()
            checked_at = utc_now()
            result = DmitCheckResult()
            try:
                products = await self.fetcher.fetch()
                result.products = len(products)
                result.available = sum(product.is_available for product in products)
                result.events_created = self.storage.sync_dmit_products(products, checked_at)

                for user in self.storage.list_dmit_subscribers():
                    for event in self.storage.list_unsent_dmit_events(user):
                        try:
                            await bot.send_message(
                                chat_id=user.user_id,
                                text=format_dmit_event(event),
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("立即购买", url=event.order_url)]]
                                ),
                            )
                            self.storage.record_dmit_notification(user.user_id, event.id)
                            result.messages_sent += 1
                        except Forbidden:
                            logger.warning("用户 %s 已阻止机器人，自动暂停", user.user_id)
                            self.storage.set_active(user.user_id, False)
                            break
                        except TelegramError as exc:
                            logger.warning(
                                "向用户 %s 推送 DMIT 补货失败：%s",
                                user.user_id,
                                type(exc).__name__,
                            )
                            break
            except DmitFetchError as exc:
                result.error = str(exc)
                logger.error("DMIT 库存任务失败：%s", exc)
            except Exception:
                result.error = "内部错误"
                logger.exception("DMIT 库存任务发生未处理异常")

            result.duration_seconds = monotonic() - started
            self.last_check_at = checked_at
            self.last_result = result
            logger.info(
                "DMIT 库存任务完成：套餐=%s 可购买=%s 补货=%s 推送=%s 耗时=%.3fs 错误=%s",
                result.products,
                result.available,
                result.events_created,
                result.messages_sent,
                result.duration_seconds,
                result.error,
            )
            return result
