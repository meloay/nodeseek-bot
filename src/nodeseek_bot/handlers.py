from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .bwh_service import BwhMonitorService
from .config import Config
from .dmit_service import LOCATION_NAMES, NETWORK_NAMES, DmitMonitorService
from .models import UTC_PLUS_8, BwhProduct, DmitProduct
from .service import MonitorService
from .storage import Storage

HELP_TEXT = """我会监控 NodeSeek 新帖标题并在命中关键字时通知你。

/add <关键字> — 添加关键字；多个关键字请用逗号分隔
/remove <关键字> — 删除关键字
/list — 查看关键字
/clear — 清空所有关键字
/interval <分钟> — 设置检查间隔
/status — 查看运行状态
/pause — 暂停通知
/resume — 恢复通知
/dmit_on — 开启 DMIT 补货通知
/dmit_off — 关闭 DMIT 补货通知
/dmit_status — 查看 DMIT 库存监控状态
/bwh_on — 开启 BandwagonHost 补货通知
/bwh_off — 关闭 BandwagonHost 补货通知
/bwh_status — 查看 BandwagonHost 库存监控状态
/help — 查看帮助

含空格的短语可以直接添加，例如：/add 香港 VPS
多个关键字示例：/add VPS, 优惠, 流量包"""

DMIT_LOCATION_FLAGS = {"hkg": "🇭🇰", "lax": "🇺🇸", "tyo": "🇯🇵"}
BWH_REGION_FLAGS = {
    "amsterdam": "🇳🇱",
    "dubai": "🇦🇪",
    "fremont": "🇺🇸",
    "hong kong": "🇭🇰",
    "los angeles": "🇺🇸",
    "new york": "🇺🇸",
    "osaka": "🇯🇵",
    "san jose": "🇺🇸",
    "singapore": "🇸🇬",
    "tokyo": "🇯🇵",
    "vancouver": "🇨🇦",
    "多地区": "🌐",
}


class BotHandlers:
    def __init__(
        self,
        config: Config,
        storage: Storage,
        service: MonitorService,
        dmit_service: DmitMonitorService,
        bwh_service: BwhMonitorService,
    ) -> None:
        self.config = config
        self.storage = storage
        self.service = service
        self.dmit_service = dmit_service
        self.bwh_service = bwh_service

    def _ensure_user(self, update: Update) -> int:
        user = update.effective_user
        if user is None:
            raise RuntimeError("缺少 Telegram 用户信息")
        self.storage.ensure_user(user.id, user.username)
        return user.id

    @staticmethod
    def _inventory_chunks(header: str, lines: list[str], limit: int = 3500) -> list[str]:
        if not lines:
            return [header + "\n\n当前没有可购买套餐。"]
        chunks: list[str] = []
        current = header
        for line in lines:
            candidate = current + "\n\n" + line
            if len(candidate) > limit and current != header:
                chunks.append(current)
                current = header + "（续）\n\n" + line
            else:
                current = candidate
        chunks.append(current)
        return chunks

    @staticmethod
    def _button_rows(
        buttons: list[InlineKeyboardButton], columns: int = 2
    ) -> list[list[InlineKeyboardButton]]:
        return [buttons[index : index + columns] for index in range(0, len(buttons), columns)]

    @staticmethod
    def _short_label(value: str, limit: int = 58) -> str:
        return value if len(value) <= limit else value[: limit - 1] + "…"

    @staticmethod
    def _callback_key(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _bwh_regions(datacenters: tuple[str, ...]) -> set[str]:
        return {item.split(" · ", 1)[0].strip() for item in datacenters if item.strip()} or {"其他"}

    @staticmethod
    def _flagged_dmit_location(location: str) -> str:
        key = location.casefold()
        name = LOCATION_NAMES.get(key, location.upper())
        flag = DMIT_LOCATION_FLAGS.get(key, "📍")
        return f"{flag} {name}"

    @staticmethod
    def _flagged_bwh_region(region: str) -> str:
        key = region.casefold()
        flag = "🌐" if key.startswith("ecommerce") else BWH_REGION_FLAGS.get(key, "📍")
        return f"{flag} {region}"

    @staticmethod
    def _compact_bwh_price(price: str) -> str:
        match = re.search(r"(\$[\d,.]+)\s*/\s*(\S+)", price)
        return f"{match.group(1)}/{match.group(2)}" if match else price.replace("USD ", "")

    @classmethod
    def _compact_bwh_label(cls, product: BwhProduct, selected_region: str | None = None) -> str:
        name = str(product.name).upper()
        capacity_match = re.search(r"\b(\d+G)\b", name)
        capacity = capacity_match.group(1) if capacity_match else ""

        if name.startswith("SPECIAL "):
            family = f"SPECIAL系列 {capacity}".strip()
        elif "ECOMMERCE SLA" in name:
            family = f"ECOMMERCE SLA {capacity}".strip()
        elif "PROMO" in name:
            family = f"PROMO系列 {capacity}".strip()
        else:
            tier = product.tiers[0] if product.tiers else "VPS"
            family = f"{tier} {capacity}".strip()

        destination = selected_region.upper() if selected_region else ""
        if not destination:
            for location in ("HONG KONG", "TOKYO", "OSAKA", "SINGAPORE", "LOS ANGELES"):
                if location in name:
                    destination = location
                    break
        if not destination and "ECOMMERCE" in name:
            bandwidth = re.search(r"HIBW\s+\d+T", name)
            destination = "ECOMMERCE" + (f" {bandwidth.group(0)}" if bandwidth else "")
        if not destination:
            destination = "多地区"

        price = cls._compact_bwh_price(product.price)
        destination = cls._flagged_bwh_region(destination)
        return f"{family} - {destination} - {price}"

    @staticmethod
    def _dmit_coupon_notes(products: list[DmitProduct]) -> list[str]:
        notes: set[str] = set()
        eligible_plans = ("STARTER", "MINI", "MICRO", "MEDIUM", "LARGE", "GIANT")
        for product in products:
            if product.network.casefold() not in {"lite", "standard"}:
                continue
            if not product.name.upper().startswith(eligible_plans):
                continue
            billing = product.price.casefold()
            if "半年" in billing or "semi" in billing:
                notes.add("Lite-Semi-Annually-Recur-20OFF（半年付 20% 循环）")
            elif "年" in billing or "annual" in billing:
                notes.add("Lite-Annually-Recur-30OFF（年付 30% 循环）")
        return sorted(notes)

    def _dmit_grouped_products(self, mode: str) -> dict[str, list]:
        grouped: dict[str, list] = defaultdict(list)
        for product in self.storage.list_available_dmit_products():
            if mode == "region":
                key = product.location.casefold() or "other"
            else:
                key = f"{product.network.casefold()}|{product.hardware.casefold()}"
            grouped[key].append(product)
        return dict(grouped)

    def _bwh_grouped_products(self, mode: str) -> dict[str, list]:
        grouped: dict[str, list] = defaultdict(list)
        for product in self.storage.list_available_bwh_products():
            values = product.tiers or ("未分类",)
            if mode == "region":
                values = tuple(self._bwh_regions(product.datacenters))
            for value in values:
                grouped[value].append(product)
        return dict(grouped)

    @staticmethod
    def _dmit_group_label(mode: str, key: str) -> str:
        if mode == "region":
            return BotHandlers._flagged_dmit_location(key)
        network, _, hardware = key.partition("|")
        network_name = NETWORK_NAMES.get(network, network.upper())
        return f"{network_name} · {hardware.upper()}"

    def _stock_menu_view(self, provider: str, mode: str) -> tuple[str, InlineKeyboardMarkup]:
        if provider == "dmit":
            grouped = self._dmit_grouped_products(mode)
            provider_name = "DMIT"
        else:
            grouped = self._bwh_grouped_products(mode)
            provider_name = "BandwagonHost"

        def label_for(key: str) -> str:
            if provider == "dmit":
                return self._dmit_group_label(mode, key)
            return self._flagged_bwh_region(key) if mode == "region" else key

        mode_name = "地区" if mode == "region" else "系列"
        choices = sorted(grouped, key=str.casefold)
        buttons = [
            InlineKeyboardButton(
                self._short_label(f"{label_for(key)}（{len(grouped[key])}）"),
                callback_data=(f"stock:{provider}:{mode}:{self._callback_key(key)}"),
            )
            for key in choices
        ]
        rows = self._button_rows(buttons)
        rows.append([InlineKeyboardButton("⬅️ 返回状态", callback_data=f"stock:{provider}:home")])
        text = f"{provider_name} 可购买套餐 · 按{mode_name}\n\n请选择{mode_name}："
        if not choices:
            text = f"{provider_name} 当前没有可购买套餐。"
        return text, InlineKeyboardMarkup(rows)

    def _stock_detail_view(
        self, provider: str, mode: str, selected_key: str
    ) -> tuple[str, InlineKeyboardMarkup]:
        if provider == "dmit":
            grouped = self._dmit_grouped_products(mode)
            provider_name = "DMIT"
            group_label = self._dmit_group_label(mode, selected_key)
        else:
            grouped = self._bwh_grouped_products(mode)
            provider_name = "BandwagonHost"
            group_label = (
                self._flagged_bwh_region(selected_key) if mode == "region" else selected_key
            )
        products = grouped.get(selected_key, [])
        mode_name = "地区" if mode == "region" else "系列"
        rows: list[list[InlineKeyboardButton]] = []
        for product in products:
            if provider == "dmit":
                if mode == "region":
                    network = NETWORK_NAMES.get(product.network.casefold(), product.network)
                    context_label = f"{network} · {product.hardware.upper()}"
                else:
                    context_label = self._flagged_dmit_location(product.location)
                label = f"{context_label} · {product.name} · {product.price}"
            else:
                selected_region = selected_key if mode == "region" else None
                label = self._compact_bwh_label(product, selected_region)
            if product.order_url:
                rows.append([InlineKeyboardButton(self._short_label(label), url=product.order_url)])
        rows.append(
            [
                InlineKeyboardButton(
                    f"⬅️ 返回{mode_name}", callback_data=f"stock:{provider}:menu:{mode}"
                )
            ]
        )
        coupon_notes = self._dmit_coupon_notes(products) if provider == "dmit" else []
        coupon_text = (
            "🎟 优惠码：" + "；".join(coupon_notes)
            if coupon_notes
            else "🎟 优惠码：暂未查到当前分类可用的官方优惠码"
        )
        text = (
            f"{provider_name} · {group_label}\n"
            f"可购买套餐：{len(products)} 个\n\n"
            f"{coupon_text}\n\n"
            "点击套餐名称即可前往购买页。"
        )
        if not products:
            text = f"{provider_name} · {group_label}\n\n该分类的库存已更新，请返回重新选择。"
        return text, InlineKeyboardMarkup(rows)

    def _resolve_stock_selection(self, provider: str, mode: str, digest: str) -> str | None:
        grouped = (
            self._dmit_grouped_products(mode)
            if provider == "dmit"
            else self._bwh_grouped_products(mode)
        )
        return next((key for key in grouped if self._callback_key(key) == digest), None)

    def _dmit_home_view(self, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        user = self.storage.get_user(user_id)
        assert user
        available, unavailable = self.storage.dmit_stock_counts()
        last_check = (
            self.dmit_service.last_check_at.astimezone(UTC_PLUS_8).strftime(
                "%Y-%m-%d %H:%M:%S UTC+8"
            )
            if self.dmit_service.last_check_at
            else "尚未执行"
        )
        result = "正常"
        if self.dmit_service.last_result and self.dmit_service.last_result.error:
            result = f"异常（{self.dmit_service.last_result.error}）"
        text = (
            "DMIT 库存监控\n"
            f"通知：{'已开启' if user.dmit_stock_enabled else '已关闭'}\n"
            f"可购买：{available} 个\n"
            f"缺货：{unavailable} 个\n"
            f"最近检查：{last_check}\n"
            f"最近结果：{result}\n\n"
            "请选择查看方式："
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📍 按地区", callback_data="stock:dmit:menu:region"),
                    InlineKeyboardButton("🏷 按系列", callback_data="stock:dmit:menu:series"),
                ]
            ]
        )
        return text, markup

    def _bwh_home_view(self, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        user = self.storage.get_user(user_id)
        assert user
        available, unavailable = self.storage.bwh_stock_counts()
        last_check = (
            self.bwh_service.last_check_at.astimezone(UTC_PLUS_8).strftime(
                "%Y-%m-%d %H:%M:%S UTC+8"
            )
            if self.bwh_service.last_check_at
            else "尚未执行"
        )
        result = "正常"
        if self.bwh_service.last_result and self.bwh_service.last_result.error:
            result = f"异常（{self.bwh_service.last_result.error}）"
        text = (
            "BandwagonHost 库存监控\n"
            f"通知：{'已开启' if user.bwh_stock_enabled else '已关闭'}\n"
            f"可购买：{available} 个\n"
            f"缺货：{unavailable} 个\n"
            f"最近检查：{last_check}\n"
            f"最近结果：{result}\n\n"
            "请选择查看方式："
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🏷 按系列", callback_data="stock:bwh:menu:series"),
                    InlineKeyboardButton("📍 按地区", callback_data="stock:bwh:menu:region"),
                ]
            ]
        )
        return text, markup

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._ensure_user(update)
        assert update.effective_message
        await update.effective_message.reply_text(f"欢迎使用 NodeSeek 关键字监控。\n\n{HELP_TEXT}")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._ensure_user(update)
        assert update.effective_message
        await update.effective_message.reply_text(HELP_TEXT)

    async def add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        raw = " ".join(context.args).strip()
        if not raw:
            await update.effective_message.reply_text("用法：/add <关键字>，多个请用逗号分隔。")
            return
        values = [part.strip() for part in re.split(r"[,，]", raw) if part.strip()]
        if any(len(value) > 64 for value in values):
            await update.effective_message.reply_text("单个关键字不能超过 64 个字符。")
            return
        existing = self.storage.list_keywords(user_id)
        if len(existing) + len(values) > 50:
            await update.effective_message.reply_text("每位用户最多可设置 50 个关键字。")
            return
        added = [value for value in values if self.storage.add_keyword(user_id, value)]
        duplicates = len(values) - len(added)
        message = f"已添加 {len(added)} 个关键字"
        if added:
            message += "：" + "、".join(added)
        if duplicates:
            message += f"；忽略 {duplicates} 个重复项"
        await update.effective_message.reply_text(message + "。")

    async def remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        keyword = " ".join(context.args).strip()
        if not keyword:
            await update.effective_message.reply_text("用法：/remove <关键字>")
            return
        removed = self.storage.remove_keyword(user_id, keyword)
        await update.effective_message.reply_text(
            f"已删除关键字：{keyword}" if removed else f"未找到关键字：{keyword}"
        )

    async def list_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        keywords = self.storage.list_keywords(user_id)
        if not keywords:
            await update.effective_message.reply_text("尚未设置关键字，可使用 /add 添加。")
            return
        lines = [f"{index}. {item.keyword}" for index, item in enumerate(keywords, start=1)]
        await update.effective_message.reply_text("当前关键字：\n" + "\n".join(lines))

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._ensure_user(update)
        assert update.effective_message
        await update.effective_message.reply_text(
            "确定清空全部关键字吗？",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("确认清空", callback_data="clear:yes"),
                        InlineKeyboardButton("取消", callback_data="clear:no"),
                    ]
                ]
            ),
        )

    async def clear_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        if query.data == "clear:yes":
            count = self.storage.clear_keywords(user_id)
            await query.edit_message_text(f"已清空 {count} 个关键字。")
        else:
            await query.edit_message_text("已取消清空。")

    async def interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        if len(context.args) != 1:
            await update.effective_message.reply_text("用法：/interval <分钟数>")
            return
        try:
            minutes = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("分钟数必须是整数。")
            return
        minimum = self.config.users.min_interval_minutes
        maximum = self.config.users.max_interval_minutes
        if not minimum <= minutes <= maximum:
            await update.effective_message.reply_text(
                f"检查间隔必须在 {minimum}～{maximum} 分钟之间。"
            )
            return
        self.storage.set_interval(user_id, minutes)
        await update.effective_message.reply_text(f"检查间隔已设置为 {minutes} 分钟。")

    async def pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_active(user_id, False)
        await update.effective_message.reply_text("推送已暂停。")

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_active(user_id, True)
        await update.effective_message.reply_text("推送已恢复；暂停期间的历史帖子不会补发。")

    async def dmit_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_dmit_enabled(user_id, True)
        await update.effective_message.reply_text(
            "DMIT 补货通知已开启。只通知开启后的新补货，不补发当前已有库存。"
        )

    async def dmit_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_dmit_enabled(user_id, False)
        await update.effective_message.reply_text("DMIT 补货通知已关闭。")

    async def dmit_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        text, markup = self._dmit_home_view(user_id)
        await update.effective_message.reply_text(text, reply_markup=markup)

    async def bwh_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_bwh_enabled(user_id, True)
        await update.effective_message.reply_text(
            "BandwagonHost 补货通知已开启。只通知开启后的新补货，不补发当前已有库存。"
        )

    async def bwh_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        self.storage.set_bwh_enabled(user_id, False)
        await update.effective_message.reply_text("BandwagonHost 补货通知已关闭。")

    async def bwh_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        text, markup = self._bwh_home_view(user_id)
        await update.effective_message.reply_text(text, reply_markup=markup)

    async def stock_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        user_id = self._ensure_user(update)
        parts = (query.data or "").split(":")
        if len(parts) < 3 or parts[0] != "stock" or parts[1] not in {"dmit", "bwh"}:
            return
        provider = parts[1]
        action = parts[2]
        if action == "home" and len(parts) == 3:
            view = (
                self._dmit_home_view(user_id)
                if provider == "dmit"
                else self._bwh_home_view(user_id)
            )
        elif action == "menu" and len(parts) == 4 and parts[3] in {"region", "series"}:
            view = self._stock_menu_view(provider, parts[3])
        elif action in {"region", "series"} and len(parts) == 4:
            selected = self._resolve_stock_selection(provider, action, parts[3])
            if selected is None:
                view = self._stock_menu_view(provider, action)
            else:
                view = self._stock_detail_view(provider, action, selected)
        else:
            return
        await query.edit_message_text(view[0], reply_markup=view[1])

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = self._ensure_user(update)
        assert update.effective_message
        user = self.storage.get_user(user_id)
        assert user
        keyword_count = len(self.storage.list_keywords(user_id))
        uptime = timedelta(
            seconds=int((datetime.now(timezone.utc) - self.service.started_at).total_seconds())
        )
        last_check = (
            self.service.last_check_at.astimezone(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S UTC+8")
            if self.service.last_check_at
            else "尚未执行"
        )
        last_result = "正常"
        if self.service.last_result and self.service.last_result.error:
            last_result = f"异常（{self.service.last_result.error}）"
        await update.effective_message.reply_text(
            "监控状态\n"
            f"状态：{'运行中' if user.is_active else '已暂停'}\n"
            f"关键字：{keyword_count} 个\n"
            f"检查间隔：{user.check_interval} 分钟\n"
            f"DMIT 补货：{'已开启' if user.dmit_stock_enabled else '已关闭'}\n"
            f"BandwagonHost 补货：{'已开启' if user.bwh_stock_enabled else '已关闭'}\n"
            f"运行时长：{uptime}\n"
            f"最近抓取：{last_check}\n"
            f"最近结果：{last_result}"
        )
