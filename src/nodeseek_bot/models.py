from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Post:
    post_id: str
    title: str
    link: str
    author: str = "未知"
    category: str = "未分类"
    published_at: datetime | None = None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class User:
    user_id: int
    username: str | None
    is_active: bool
    check_interval: int
    match_scope: str
    created_at: datetime
    updated_at: datetime
    delivery_since: datetime
    last_checked_at: datetime | None
    dmit_stock_enabled: bool = False
    dmit_enabled_since: datetime | None = None
    bwh_stock_enabled: bool = False
    bwh_enabled_since: datetime | None = None


@dataclass(frozen=True, slots=True)
class Keyword:
    id: int
    user_id: int
    keyword: str
    match_mode: str
    is_exclude: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DmitProduct:
    product_key: str
    name: str
    location: str
    network: str
    hardware: str
    specs: tuple[str, ...]
    price: str
    is_available: bool
    order_url: str | None


@dataclass(frozen=True, slots=True)
class DmitStockEvent:
    id: int
    product_key: str
    name: str
    location: str
    network: str
    hardware: str
    specs: tuple[str, ...]
    price: str
    order_url: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BwhProduct:
    product_key: str
    name: str
    tiers: tuple[str, ...]
    datacenters: tuple[str, ...]
    specs: tuple[str, ...]
    price: str
    is_available: bool
    order_url: str | None


@dataclass(frozen=True, slots=True)
class BwhStockEvent:
    id: int
    product_key: str
    name: str
    tiers: tuple[str, ...]
    datacenters: tuple[str, ...]
    specs: tuple[str, ...]
    price: str
    order_url: str
    created_at: datetime
