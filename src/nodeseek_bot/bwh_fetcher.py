from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from curl_cffi import requests as curl_requests

from .config import BwhConfig
from .models import BwhProduct

logger = logging.getLogger(__name__)


class BwhFetchError(RuntimeError):
    pass


PERIOD_NAMES = {
    "Monthly": "月",
    "Quarterly": "季度",
    "Semi-Annually": "半年",
    "Annually": "年",
}


def _affiliate_order_url(prefix: str, pid: int) -> str:
    parts = urlsplit(prefix)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "pid"]
    query.append(("pid", str(pid)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _capacity(value: int, unit: str) -> str:
    if unit == "MB" and value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000} TB"
    if unit == "MB" and value >= 1000 and value % 1000 == 0:
        return f"{value // 1000} GB"
    return f"{value} {unit}"


def _ram(value: int) -> str:
    if value % 1024 == 0:
        return f"{value // 1024} GB"
    return f"{value} MB"


def _link(value: int) -> str:
    if value % 1000 == 0:
        return f"{value // 1000} Gbps"
    return f"{value} Mbps"


def _price(prices: list[dict[str, Any]]) -> str:
    first = prices[0]
    cents = int(first["cents"])
    currency = str(first.get("currency") or "USD")
    period = PERIOD_NAMES.get(str(first.get("period")), str(first.get("period") or ""))
    return f"{currency} ${cents / 100:.2f} / {period}"


def parse_bwh_inventory(data: object, affiliate_url_prefix: str) -> list[BwhProduct]:
    if not isinstance(data, dict):
        raise BwhFetchError("BandwagonHost 库存接口返回格式异常")
    raw_products = data.get("products")
    tiers = data.get("tiers")
    locations = data.get("locations")
    if not isinstance(raw_products, list) or len(raw_products) < 10:
        count = len(raw_products) if isinstance(raw_products, list) else 0
        raise BwhFetchError(f"BandwagonHost 库存接口异常，仅解析到 {count} 个套餐")
    if not isinstance(tiers, list) or not isinstance(locations, list):
        raise BwhFetchError("BandwagonHost 系列或机房数据缺失")

    tier_names = {
        str(item["id"]): str(item["name"])
        for item in tiers
        if isinstance(item, dict) and item.get("id") and item.get("name")
    }
    datacenter_names: dict[str, str] = {}
    for location in locations:
        if not isinstance(location, dict):
            continue
        city = str(location.get("city") or "未知地区")
        for datacenter in location.get("datacenters") or []:
            if not isinstance(datacenter, dict) or not datacenter.get("id"):
                continue
            dc_id = str(datacenter["id"])
            dc_name = str(datacenter.get("name") or dc_id)
            datacenter_names[dc_id] = f"{city} · {dc_id} {dc_name}"

    products: list[BwhProduct] = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["id"])
            name = str(item["name"]).strip()
            prices = item["prices"]
            datacenters = item["datacenters"]
            if not name or not isinstance(prices, list) or not isinstance(datacenters, dict):
                continue
            dc_labels = tuple(datacenter_names.get(str(dc_id), str(dc_id)) for dc_id in datacenters)
            available = not bool(item.get("outOfStock")) and bool(prices) and bool(dc_labels)
            product_tiers = tuple(
                tier_names.get(str(tier), str(tier)) for tier in item.get("tiers") or []
            )
            specs = (
                f"硬盘 {_capacity(int(item['ssd']), 'MB')}",
                f"内存 {_ram(int(item['ram']))}",
                f"CPU {int(item['cpu'])} 核",
                f"流量 {_capacity(int(item['transfer']), 'MB')}/月",
                f"端口 {_link(int(item['link']))}",
            )
            products.append(
                BwhProduct(
                    product_key=str(pid),
                    name=name,
                    tiers=product_tiers,
                    datacenters=dc_labels,
                    specs=specs,
                    price=_price(prices),
                    is_available=available,
                    order_url=(
                        _affiliate_order_url(affiliate_url_prefix, pid) if available else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError, IndexError):
            continue

    if len(products) < 10:
        raise BwhFetchError(f"BandwagonHost 套餐字段异常，仅解析到 {len(products)} 个套餐")
    keys = [product.product_key for product in products]
    if len(keys) != len(set(keys)):
        raise BwhFetchError("BandwagonHost 库存接口包含重复套餐 ID")
    return products


class BwhFetcher:
    def __init__(self, config: BwhConfig) -> None:
        self.config = config

    async def fetch(self) -> list[BwhProduct]:
        last_error: Exception | None = None
        urls = tuple(dict.fromkeys((self.config.url, self.config.fallback_url)))
        for attempt in range(1, self.config.retry_times + 1):
            for url in urls:
                try:
                    response = await asyncio.to_thread(
                        curl_requests.get,
                        url,
                        impersonate=self.config.impersonate,
                        timeout=self.config.timeout_seconds,
                    )
                    response.raise_for_status()
                    products = parse_bwh_inventory(
                        response.json(), self.config.affiliate_url_prefix
                    )
                    logger.info(
                        "BandwagonHost 库存抓取成功：域名=%s 套餐=%s",
                        urlsplit(url).hostname,
                        len(products),
                    )
                    return products
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "BandwagonHost 库存抓取失败（域名=%s 第 %s/%s 次）：%s",
                        urlsplit(url).hostname,
                        attempt,
                        self.config.retry_times,
                        type(exc).__name__,
                    )
            if attempt < self.config.retry_times:
                await asyncio.sleep(min(2 ** (attempt - 1), 30))
        raise BwhFetchError("BandwagonHost 两个域名的库存抓取均失败") from last_error
