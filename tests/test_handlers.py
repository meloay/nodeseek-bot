from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus, ChatType

from nodeseek_bot.handlers import BotHandlers
from nodeseek_bot.models import BwhProduct, DmitProduct
from nodeseek_bot.storage import Storage


def make_handlers(tmp_path: Path) -> BotHandlers:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    storage.ensure_user(1, "alice")
    storage.sync_dmit_products(
        [
            DmitProduct(
                "hkg.premium.as3.tiny",
                "TINY",
                "hkg",
                "premium",
                "as3",
                ("1 vCPU", "1 GB RAM"),
                "$39.90 USD/月",
                True,
                "https://www.dmit.io/aff.php?aff=13497&pid=129&language=chinese",
            ),
            DmitProduct(
                "lax.premium.as3.micro",
                "MICRO",
                "lax",
                "premium",
                "as3",
                ("2 vCPU", "2 GB RAM"),
                "$59.90 USD/月",
                True,
                "https://www.dmit.io/aff.php?aff=13497&pid=265&language=chinese",
            ),
        ]
    )
    storage.sync_bwh_products(
        [
            BwhProduct(
                "100",
                "SPECIAL 40G KVM PROMO V5 - HONG KONG CN2 GIA",
                ("Ultra VPS",),
                ("Hong Kong · HK_8 Equinix HK2",),
                ("硬盘 20 GB",),
                "USD $89.99 / 月",
                True,
                "https://bandwagonhost.com/aff.php?aff=65719&pid=100",
            )
        ]
    )
    service = SimpleNamespace(last_check_at=None, last_result=None)
    return BotHandlers(None, storage, service, service, service)  # type: ignore[arg-type]


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self, status: str) -> None:
        self.status = status
        self.member_checks: list[tuple[int, int]] = []

    async def get_chat_member(self, chat_id: int, user_id: int) -> SimpleNamespace:
        self.member_checks.append((chat_id, user_id))
        return SimpleNamespace(status=self.status)


def group_update(message: FakeMessage) -> SimpleNamespace:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(
            id=-1001234567890,
            type=ChatType.SUPERGROUP,
            username="market_group",
            title="机器交易群",
        ),
        effective_user=SimpleNamespace(id=42, username="alice", full_name="Alice"),
        effective_message=message,
        callback_query=None,
    )


@pytest.mark.asyncio
async def test_group_admin_can_configure_group_subscription(tmp_path: Path) -> None:
    handlers = make_handlers(tmp_path)
    message = FakeMessage()
    bot = FakeBot(ChatMemberStatus.ADMINISTRATOR)
    context = SimpleNamespace(args=["VPS"], bot=bot)

    await handlers.add(group_update(message), context)  # type: ignore[arg-type]

    subscriber = handlers.storage.get_user(-1001234567890)
    assert subscriber
    assert subscriber.chat_type == ChatType.SUPERGROUP
    assert subscriber.chat_title == "机器交易群"
    assert [item.keyword for item in handlers.storage.list_keywords(subscriber.user_id)] == [
        "VPS"
    ]
    assert bot.member_checks == [(-1001234567890, 42)]
    assert message.replies == ["已添加 1 个关键字：VPS。"]


@pytest.mark.asyncio
async def test_group_member_cannot_change_group_subscription(tmp_path: Path) -> None:
    handlers = make_handlers(tmp_path)
    message = FakeMessage()
    context = SimpleNamespace(args=["VPS"], bot=FakeBot(ChatMemberStatus.MEMBER))

    await handlers.add(group_update(message), context)  # type: ignore[arg-type]

    assert handlers.storage.get_user(-1001234567890) is None
    assert message.replies == ["群组中只有管理员可以修改监控配置。"]


def test_inventory_chunks_preserve_all_lines_within_limit() -> None:
    lines = [f"<b>{index}. PLAN-{index}</b>\n💵 $10\n🔗 购买" for index in range(100)]
    chunks = BotHandlers._inventory_chunks("<b>库存状态</b>", lines, limit=500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert sum(chunk.count("🔗 购买") for chunk in chunks) == 100


def test_dmit_stock_menu_groups_and_links_products(tmp_path: Path) -> None:
    handlers = make_handlers(tmp_path)
    text, menu = handlers._stock_menu_view("dmit", "region")
    assert "按地区" in text
    buttons = [button for row in menu.inline_keyboard for button in row]
    assert {button.text for button in buttons} >= {"🇭🇰 香港（1）", "🇺🇸 洛杉矶（1）"}
    assert all(
        len(button.callback_data.encode("utf-8")) <= 64
        for button in buttons
        if button.callback_data
    )

    selected = handlers._resolve_stock_selection("dmit", "region", handlers._callback_key("hkg"))
    assert selected == "hkg"
    detail_text, detail = handlers._stock_detail_view("dmit", "region", selected)
    assert "TINY" not in detail_text
    assert "可购买套餐：1 个" in detail_text
    assert "暂未查到当前分类可用的官方优惠码" in detail_text
    assert detail.inline_keyboard[0][0].url
    assert "aff=13497" in detail.inline_keyboard[0][0].url
    assert "TINY" in detail.inline_keyboard[0][0].text


def test_bwh_stock_menu_supports_series_and_region(tmp_path: Path) -> None:
    handlers = make_handlers(tmp_path)
    _, series_menu = handlers._stock_menu_view("bwh", "series")
    _, region_menu = handlers._stock_menu_view("bwh", "region")
    assert series_menu.inline_keyboard[0][0].text == "Ultra VPS（1）"
    assert region_menu.inline_keyboard[0][0].text == "🇭🇰 Hong Kong（1）"

    detail_text, detail = handlers._stock_detail_view("bwh", "series", "Ultra VPS")
    assert "可购买套餐：1 个" in detail_text
    assert detail.inline_keyboard[0][0].url
    assert "aff=65719" in detail.inline_keyboard[0][0].url
    assert detail.inline_keyboard[0][0].text == "SPECIAL系列 40G - 🇭🇰 HONG KONG - $89.99/月"


def test_bwh_compact_labels_keep_payment_period() -> None:
    annual = BwhProduct(
        "101",
        "20G KVM - PROMO",
        ("Basic VPS",),
        ("Amsterdam · EUNL_2", "Los Angeles · USCA_2"),
        (),
        "USD $49.99 / 年",
        True,
        "https://example.com",
    )
    quarterly = BwhProduct(
        "102",
        "SPECIAL 20G KVM PROMO V5 - CN2 GIA ECOMMERCE",
        ("E-Commerce VPS",),
        ("Los Angeles · USCA_6",),
        (),
        "USD $49.99 / 季度",
        True,
        "https://example.com",
    )
    assert BotHandlers._compact_bwh_label(annual) == "PROMO系列 20G - 🌐 多地区 - $49.99/年"
    assert BotHandlers._compact_bwh_label(quarterly) == (
        "SPECIAL系列 20G - 🌐 ECOMMERCE - $49.99/季度"
    )
    assert BotHandlers._compact_bwh_label(quarterly, "Amsterdam") == (
        "SPECIAL系列 20G - 🇳🇱 AMSTERDAM - $49.99/季度"
    )


def test_dmit_coupon_only_appears_for_eligible_lite_billing_cycle() -> None:
    eligible = DmitProduct(
        "lax.lite.as3.starter",
        "STARTER",
        "lax",
        "lite",
        "as3",
        (),
        "$100 USD / 年",
        True,
        "https://example.com",
    )
    ineligible = DmitProduct(
        "hkg.tier1.as3.starter",
        "STARTER",
        "hkg",
        "tier1",
        "as3",
        (),
        "$100 USD / 年",
        True,
        "https://example.com",
    )
    assert BotHandlers._dmit_coupon_notes([eligible]) == [
        "Lite-Annually-Recur-30OFF（年付 30% 循环）"
    ]
    assert BotHandlers._dmit_coupon_notes([ineligible]) == []
