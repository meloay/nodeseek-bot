from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from nodeseek_bot.bwh_fetcher import parse_bwh_inventory
from nodeseek_bot.bwh_service import format_bwh_event
from nodeseek_bot.models import BwhProduct, BwhStockEvent, utc_now
from nodeseek_bot.storage import Storage


def inventory_data(out_of_stock: set[int] | None = None) -> dict[str, object]:
    unavailable = out_of_stock or set()
    return {
        "tiers": [{"id": "basic", "name": "Basic VPS"}],
        "locations": [
            {
                "city": "Los Angeles",
                "country": "United States",
                "datacenters": [{"id": "USCA_2", "name": "Coresite LA2"}],
            }
        ],
        "products": [
            {
                "id": 100 + index,
                "name": f"PLAN-{index}",
                "ssd": 20000,
                "ram": 1024,
                "cpu": 2,
                "transfer": 1000000,
                "link": 1000,
                "prices": [{"cents": 4999, "currency": "USD", "period": "Annually"}],
                "outOfStock": index in unavailable,
                "tiers": ["basic"],
                "datacenters": {"USCA_2": 35},
                "dcOption": 10,
            }
            for index in range(10)
        ],
    }


def test_parse_bwh_inventory_and_affiliate_links() -> None:
    products = parse_bwh_inventory(
        inventory_data({1}), "https://bandwagonhost.com/aff.php?aff=65719"
    )
    assert len(products) == 10
    assert products[0].product_key == "100"
    assert products[0].is_available
    assert products[0].order_url == "https://bandwagonhost.com/aff.php?aff=65719&pid=100"
    assert products[0].specs == (
        "硬盘 20 GB",
        "内存 1 GB",
        "CPU 2 核",
        "流量 1 TB/月",
        "端口 1 Gbps",
    )
    assert products[0].price == "USD $49.99 / 年"
    assert products[0].datacenters == ("Los Angeles · USCA_2 Coresite LA2",)
    assert not products[1].is_available
    assert products[1].order_url is None


def test_bwh_transition_creates_retryable_event(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    storage.ensure_user(1, "alice")
    storage.set_bwh_enabled(1, True)
    baseline_time = utc_now()
    unavailable = BwhProduct(
        "42",
        "THE PLAN",
        ("Basic VPS",),
        ("Los Angeles · USCA_2 Coresite LA2",),
        ("硬盘 20 GB", "内存 1 GB"),
        "USD $49.99 / 年",
        False,
        None,
    )
    available = replace(
        unavailable,
        is_available=True,
        order_url="https://bandwagonhost.com/aff.php?aff=65719&pid=42",
    )
    assert storage.sync_bwh_products([unavailable], baseline_time) == 0
    event_time = baseline_time + timedelta(seconds=1)
    assert storage.sync_bwh_products([available], event_time) == 1
    listed = storage.list_available_bwh_products()
    assert len(listed) == 1
    assert listed[0].name == "THE PLAN"
    assert listed[0].order_url == available.order_url
    user = storage.get_user(1)
    assert user and user.bwh_stock_enabled
    events = storage.list_unsent_bwh_events(user)
    assert len(events) == 1
    assert events[0].name == "THE PLAN"
    assert storage.record_bwh_notification(1, events[0].id)
    assert storage.list_unsent_bwh_events(user) == []


def test_format_bwh_event_is_chinese_and_utc8() -> None:
    event = BwhStockEvent(
        1,
        "42",
        "THE PLAN",
        ("Basic VPS",),
        ("Los Angeles · USCA_2 Coresite LA2",),
        ("硬盘 20 GB", "内存 1 GB"),
        "USD $49.99 / 年",
        "https://bandwagonhost.com/aff.php?aff=65719&pid=42",
        utc_now(),
    )
    message = format_bwh_event(event)
    assert "BandwagonHost 套餐补货" in message
    assert "Los Angeles" in message
    assert "UTC+8" in message
