from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from nodeseek_bot.dmit_fetcher import DmitFetchError, parse_dmit_cart
from nodeseek_bot.dmit_service import format_dmit_event
from nodeseek_bot.models import DmitProduct, DmitStockEvent, utc_now
from nodeseek_bot.storage import Storage


def cart_html(available_indexes: set[int]) -> str:
    products = []
    for index in range(60):
        stock_class = "" if index in available_indexes else "none-stock"
        products.append(
            f"""
            <div class="cart-products-item" gid="31">
              <div class="cart-products-box {stock_class}" pid="{100 + index}">
                <div class="cart-products-title">LAX.AS3.Pro.PLAN-{index}</div>
                <div class="price-num">{index + 1}.90</div>
                <div class="price-suffix">USD</div>
                <div class="billing-cycle-text">/ 月繳</div>
                <div class="products-desc-item">
                  <div class="desc-item-title">虛擬核心</div>
                  <div class="desc-item-value">{index + 1} vCores</div>
                </div>
                <div class="products-desc-item">
                  <div class="desc-item-title">記憶體</div>
                  <div class="desc-item-value">2.0GB</div>
                </div>
              </div>
            </div>
            """
        )
    return "".join(products)


def test_parse_dmit_cart_uses_authoritative_stock_class() -> None:
    products = parse_dmit_cart(cart_html({0, 3}))
    assert len(products) == 60
    assert products[0].product_key == "lax.premium.as3.plan-0"
    assert products[0].is_available
    assert products[0].order_url == (
        "https://www.dmit.io/aff.php?aff=13497&pid=100&language=chinese"
    )
    assert products[0].specs == ("虛擬核心 1 vCores", "記憶體 2.0GB")
    assert products[0].price == "$ 1.90 USD / 月繳"
    assert not products[1].is_available
    assert products[1].order_url is None


def test_parse_rejects_challenge_or_broken_page() -> None:
    with pytest.raises(DmitFetchError, match="购物车结构异常"):
        parse_dmit_cart("<html>Just a moment...</html>")


def test_stock_transition_creates_one_retryable_event(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    storage.ensure_user(1, "alice")
    storage.set_dmit_enabled(1, True)
    baseline_time = utc_now()
    unavailable = DmitProduct(
        "lax.premium.an4.mini",
        "MINI",
        "lax",
        "premium",
        "an4",
        ("4 vCore", "4GB RAM"),
        "$ 72.90/Monthly",
        False,
        None,
    )
    available = replace(
        unavailable,
        is_available=True,
        order_url="https://www.dmit.io/cart.php?a=add&pid=42",
    )
    assert storage.sync_dmit_products([unavailable], baseline_time) == 0
    event_time = baseline_time + timedelta(seconds=1)
    assert storage.sync_dmit_products([available], event_time) == 1
    listed = storage.list_available_dmit_products()
    assert len(listed) == 1
    assert listed[0].name == "MINI"
    assert listed[0].order_url == available.order_url
    user = storage.get_user(1)
    assert user
    events = storage.list_unsent_dmit_events(user)
    assert len(events) == 1
    assert events[0].name == "MINI"
    assert storage.record_dmit_notification(1, events[0].id)
    assert storage.list_unsent_dmit_events(user) == []
    assert storage.sync_dmit_products([available], event_time + timedelta(seconds=1)) == 0


def test_format_dmit_event_uses_chinese_labels_and_utc8() -> None:
    event = DmitStockEvent(
        1,
        "lax.premium.an4.mini",
        "MINI",
        "lax",
        "premium",
        "an4",
        ("4 vCore", "4GB RAM"),
        "$ 72.90/Monthly",
        "https://www.dmit.io/cart.php?a=add&pid=42",
        utc_now(),
    )
    message = format_dmit_event(event)
    assert "洛杉矶" in message
    assert "Premium 优质网络" in message
    assert "UTC+8" in message
