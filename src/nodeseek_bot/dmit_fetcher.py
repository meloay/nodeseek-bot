from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from curl_cffi import requests as curl_requests

from .config import DmitConfig
from .models import DmitProduct

logger = logging.getLogger(__name__)


class DmitFetchError(RuntimeError):
    pass


def _classes(attrs: dict[str, str | None]) -> set[str]:
    return set((attrs.get("class") or "").split())


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _affiliate_order_url(prefix: str, pid: str) -> str:
    parts = urlsplit(prefix)
    query = [
        (key, value) for key, value in parse_qsl(parts.query) if key not in {"pid", "language"}
    ]
    query.extend((("pid", pid), ("language", "chinese")))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class DmitCartParser(HTMLParser):
    """Parse authoritative WHMCS cart inventory from one page request."""

    def __init__(self, affiliate_url_prefix: str) -> None:
        super().__init__(convert_charrefs=True)
        self.affiliate_url_prefix = affiliate_url_prefix
        self.depth = 0
        self.item_depth: int | None = None
        self.item: dict[str, object] | None = None
        self.desc_depth: int | None = None
        self.desc_title = ""
        self.desc_value = ""
        self.capture_depth: int | None = None
        self.capture_kind: str | None = None
        self.capture_parts: list[str] = []
        self.products: list[DmitProduct] = []

    def handle_starttag(self, tag: str, raw_attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        self.depth += 1
        attrs = dict(raw_attrs)
        classes = _classes(attrs)
        if "cart-products-item" in classes:
            self.item_depth = self.depth
            self.item = {
                "pid": "",
                "name": "",
                "price": "",
                "currency": "USD",
                "billing": "",
                "available": False,
                "specs": [],
            }
        elif self.item is not None and "cart-products-box" in classes:
            self.item["pid"] = attrs.get("pid") or ""
            self.item["available"] = "none-stock" not in classes
        elif self.item is not None and "products-desc-item" in classes:
            self.desc_depth = self.depth
            self.desc_title = ""
            self.desc_value = ""

        if self.item is None:
            return
        kind = None
        if "cart-products-title" in classes:
            kind = "name"
        elif "price-num" in classes:
            kind = "price"
        elif "price-suffix" in classes:
            kind = "currency"
        elif "billing-cycle-text" in classes:
            kind = "billing"
        elif "desc-item-title" in classes:
            kind = "desc_title"
        elif "desc-item-value" in classes:
            kind = "desc_value"
        if kind:
            self.capture_depth = self.depth
            self.capture_kind = kind
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.capture_kind:
            self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return

        if self.capture_depth == self.depth and self.item is not None:
            value = _text(self.capture_parts)
            if self.capture_kind == "desc_title":
                self.desc_title = value
            elif self.capture_kind == "desc_value":
                self.desc_value = value
            elif self.capture_kind:
                self.item[self.capture_kind] = value
            self.capture_depth = None
            self.capture_kind = None
            self.capture_parts = []

        if self.desc_depth == self.depth and self.item is not None:
            if self.desc_title and self.desc_value:
                specs = self.item["specs"]
                assert isinstance(specs, list)
                specs.append(f"{self.desc_title} {self.desc_value}")
            self.desc_depth = None

        if self.item_depth == self.depth and self.item is not None:
            product = self._finish_item(self.item)
            if product:
                self.products.append(product)
            self.item = None
            self.item_depth = None
        self.depth -= 1

    def _finish_item(self, item: dict[str, object]) -> DmitProduct | None:
        pid = str(item["pid"])
        full_name = str(item["name"]).strip()
        parts = full_name.split(".")
        if not pid.isdigit() or len(parts) < 4:
            return None
        location, hardware, raw_network = (part.casefold() for part in parts[:3])
        network = {
            "pro": "premium",
            "premium": "premium",
            "eb": "eyeball",
            "eyeball": "eyeball",
            "t1": "tier1",
            "tier1": "tier1",
        }.get(raw_network, raw_network)
        name = ".".join(parts[3:])
        available = bool(item["available"])
        price = f"$ {str(item['price']).strip()} {str(item['currency']).strip()}"
        billing = str(item["billing"]).strip().lstrip("/").strip()
        if billing:
            price += f" / {billing}"
        specs = item["specs"]
        assert isinstance(specs, list)
        return DmitProduct(
            product_key=f"{location}.{network}.{hardware}.{name}".casefold(),
            name=name,
            location=location,
            network=network,
            hardware=hardware,
            specs=tuple(str(value) for value in specs[:6]),
            price=price,
            is_available=available,
            order_url=(_affiliate_order_url(self.affiliate_url_prefix, pid) if available else None),
        )


def parse_dmit_cart(
    content: str,
    affiliate_url_prefix: str = "https://www.dmit.io/aff.php?aff=13497",
) -> list[DmitProduct]:
    parser = DmitCartParser(affiliate_url_prefix)
    parser.feed(content)
    if len(parser.products) < 50:
        raise DmitFetchError(f"DMIT 购物车结构异常，仅解析到 {len(parser.products)} 个套餐")
    keys = [product.product_key for product in parser.products]
    if len(keys) != len(set(keys)):
        raise DmitFetchError("DMIT 购物车包含重复套餐标识")
    return parser.products


class DmitFetcher:
    def __init__(self, config: DmitConfig) -> None:
        self.config = config

    async def fetch(self) -> list[DmitProduct]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_times + 1):
            try:
                response = await asyncio.to_thread(
                    curl_requests.get,
                    self.config.url,
                    impersonate=self.config.impersonate,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                products = parse_dmit_cart(response.text, self.config.affiliate_url_prefix)
                logger.info("DMIT 真实库存抓取成功：套餐=%s", len(products))
                return products
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "DMIT 真实库存抓取失败（第 %s/%s 次）：%s",
                    attempt,
                    self.config.retry_times,
                    type(exc).__name__,
                )
                if attempt < self.config.retry_times:
                    await asyncio.sleep(min(2 ** (attempt - 1), 30))
        raise DmitFetchError("DMIT 真实库存抓取失败") from last_error
