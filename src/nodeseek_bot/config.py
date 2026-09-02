from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    token: str
    admin_id: int | None = None


@dataclass(frozen=True, slots=True)
class RssConfig:
    url: str = "https://rss.nodeseek.com/"
    poll_interval_seconds: int = 60
    timeout_seconds: float = 10
    retry_times: int = 3
    user_agent: str = "NodeSeekKeywordBot/1.0 (+private RSS monitor)"


@dataclass(frozen=True, slots=True)
class DmitConfig:
    enabled: bool = True
    url: str = "https://www.dmit.io/cart.php?language=chinese"
    affiliate_url_prefix: str = "https://www.dmit.io/aff.php?aff=13497"
    poll_interval_seconds: int = 60
    timeout_seconds: float = 20
    retry_times: int = 3
    impersonate: str = "chrome"


@dataclass(frozen=True, slots=True)
class BwhConfig:
    enabled: bool = True
    url: str = "https://bandwagonhost.com/order/get-data"
    fallback_url: str = "https://bwh81.net/order/get-data"
    affiliate_url_prefix: str = "https://bandwagonhost.com/aff.php?aff=65719"
    poll_interval_seconds: int = 60
    timeout_seconds: float = 20
    retry_times: int = 3
    impersonate: str = "chrome"


@dataclass(frozen=True, slots=True)
class UserDefaults:
    default_interval_minutes: int = 5
    min_interval_minutes: int = 1
    max_interval_minutes: int = 1440


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    path: Path = Path("./data/nodeseek_monitor.db")
    retention_days: int = 90


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: Path = Path("./logs/app.log")


@dataclass(frozen=True, slots=True)
class Config:
    telegram: TelegramConfig
    rss: RssConfig
    dmit: DmitConfig
    bwh: BwhConfig
    users: UserDefaults
    database: DatabaseConfig
    logging: LoggingConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 {name} 必须是对象")
    return value


def load_config(path: str | Path | None = None) -> Config:
    rss_defaults = RssConfig()
    dmit_defaults = DmitConfig()
    bwh_defaults = BwhConfig()
    user_defaults = UserDefaults()
    database_defaults = DatabaseConfig()
    logging_defaults = LoggingConfig()
    config_path = Path(path or os.getenv("NODESEEK_CONFIG", "config.yaml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("配置文件根节点必须是对象")
        raw = loaded

    telegram = _section(raw, "telegram")
    rss = _section(raw, "rss")
    dmit = _section(raw, "dmit")
    bwh = _section(raw, "bwh")
    users = _section(raw, "users")
    database = _section(raw, "database")
    logging = _section(raw, "logging")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("缺少 TELEGRAM_BOT_TOKEN 环境变量")

    admin_value = os.getenv("TELEGRAM_ADMIN_ID", str(telegram.get("admin_id") or "")).strip()
    try:
        admin_id = int(admin_value) if admin_value else None
    except ValueError as exc:
        raise ConfigError("TELEGRAM_ADMIN_ID 必须是整数") from exc

    cfg = Config(
        telegram=TelegramConfig(token=token, admin_id=admin_id),
        rss=RssConfig(
            url=str(rss.get("url", rss_defaults.url)),
            poll_interval_seconds=int(
                rss.get("poll_interval_seconds", rss_defaults.poll_interval_seconds)
            ),
            timeout_seconds=float(rss.get("timeout_seconds", rss_defaults.timeout_seconds)),
            retry_times=int(rss.get("retry_times", rss_defaults.retry_times)),
            user_agent=str(rss.get("user_agent", rss_defaults.user_agent)),
        ),
        dmit=DmitConfig(
            enabled=bool(dmit.get("enabled", dmit_defaults.enabled)),
            url=str(dmit.get("url", dmit_defaults.url)),
            affiliate_url_prefix=str(
                dmit.get("affiliate_url_prefix", dmit_defaults.affiliate_url_prefix)
            ),
            poll_interval_seconds=int(
                dmit.get("poll_interval_seconds", dmit_defaults.poll_interval_seconds)
            ),
            timeout_seconds=float(dmit.get("timeout_seconds", dmit_defaults.timeout_seconds)),
            retry_times=int(dmit.get("retry_times", dmit_defaults.retry_times)),
            impersonate=str(dmit.get("impersonate", dmit_defaults.impersonate)),
        ),
        bwh=BwhConfig(
            enabled=bool(bwh.get("enabled", bwh_defaults.enabled)),
            url=str(bwh.get("url", bwh_defaults.url)),
            fallback_url=str(bwh.get("fallback_url", bwh_defaults.fallback_url)),
            affiliate_url_prefix=str(
                bwh.get("affiliate_url_prefix", bwh_defaults.affiliate_url_prefix)
            ),
            poll_interval_seconds=int(
                bwh.get("poll_interval_seconds", bwh_defaults.poll_interval_seconds)
            ),
            timeout_seconds=float(bwh.get("timeout_seconds", bwh_defaults.timeout_seconds)),
            retry_times=int(bwh.get("retry_times", bwh_defaults.retry_times)),
            impersonate=str(bwh.get("impersonate", bwh_defaults.impersonate)),
        ),
        users=UserDefaults(
            default_interval_minutes=int(
                users.get("default_interval_minutes", user_defaults.default_interval_minutes)
            ),
            min_interval_minutes=int(
                users.get("min_interval_minutes", user_defaults.min_interval_minutes)
            ),
            max_interval_minutes=int(
                users.get("max_interval_minutes", user_defaults.max_interval_minutes)
            ),
        ),
        database=DatabaseConfig(
            path=Path(os.getenv("DATABASE_PATH", database.get("path", database_defaults.path))),
            retention_days=int(database.get("retention_days", database_defaults.retention_days)),
        ),
        logging=LoggingConfig(
            level=os.getenv("LOG_LEVEL", str(logging.get("level", logging_defaults.level))).upper(),
            file=Path(logging.get("file", logging_defaults.file)),
        ),
    )

    if cfg.rss.poll_interval_seconds < 30:
        raise ConfigError("rss.poll_interval_seconds 不得小于 30 秒")
    if not 1 <= cfg.rss.retry_times <= 10:
        raise ConfigError("rss.retry_times 必须在 1 到 10 之间")
    if cfg.dmit.poll_interval_seconds < 30:
        raise ConfigError("dmit.poll_interval_seconds 不得小于 30 秒")
    if not 1 <= cfg.dmit.retry_times <= 10:
        raise ConfigError("dmit.retry_times 必须在 1 到 10 之间")
    if cfg.bwh.poll_interval_seconds < 30:
        raise ConfigError("bwh.poll_interval_seconds 不得小于 30 秒")
    if not 1 <= cfg.bwh.retry_times <= 10:
        raise ConfigError("bwh.retry_times 必须在 1 到 10 之间")
    if not 0 < cfg.users.min_interval_minutes <= cfg.users.default_interval_minutes:
        raise ConfigError("默认用户间隔不能小于最小间隔")
    if cfg.users.max_interval_minutes < cfg.users.default_interval_minutes:
        raise ConfigError("最大用户间隔不能小于默认间隔")
    return cfg
