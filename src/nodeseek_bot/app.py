from __future__ import annotations

import logging
from datetime import datetime, time
from logging.handlers import RotatingFileHandler

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
)

from .bwh_fetcher import BwhFetcher
from .bwh_service import BwhMonitorService
from .config import Config, ConfigError, load_config
from .dmit_fetcher import DmitFetcher
from .dmit_service import DmitMonitorService
from .handlers import BotHandlers
from .models import UTC_PLUS_8
from .rss_fetcher import RssFetcher
from .service import MonitorService
from .storage import Storage

logger = logging.getLogger(__name__)


class UtcPlus8Formatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        current = datetime.fromtimestamp(record.created, tz=UTC_PLUS_8)
        return current.strftime(datefmt or "%Y-%m-%dT%H:%M:%S%z")


def configure_logging(config: Config) -> None:
    config.logging.file.parent.mkdir(parents=True, exist_ok=True)
    formatter = UtcPlus8Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"
    )
    file_handler = RotatingFileHandler(
        config.logging.file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(
        level=getattr(logging, config.logging.level, logging.INFO),
        handlers=[file_handler, console_handler],
    )
    # httpx logs full request URLs at INFO level. Telegram Bot API embeds the
    # secret token in the URL path, so those records must never reach logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_application(config: Config) -> Application:
    storage = Storage(config.database.path, config.users.default_interval_minutes)
    storage.initialize()
    fetcher = RssFetcher(config.rss)
    service = MonitorService(config, storage, fetcher)
    dmit_service = DmitMonitorService(storage, DmitFetcher(config.dmit))
    bwh_service = BwhMonitorService(storage, BwhFetcher(config.bwh))
    handlers = BotHandlers(config, storage, service, dmit_service, bwh_service)

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "开始使用"),
                BotCommand("add", "添加关键字"),
                BotCommand("remove", "删除关键字"),
                BotCommand("list", "查看关键字"),
                BotCommand("clear", "清空关键字"),
                BotCommand("interval", "设置检查间隔"),
                BotCommand("status", "查看状态"),
                BotCommand("pause", "暂停推送"),
                BotCommand("resume", "恢复推送"),
                BotCommand("dmit_on", "开启 DMIT 补货通知"),
                BotCommand("dmit_off", "关闭 DMIT 补货通知"),
                BotCommand("dmit_status", "查看 DMIT 库存状态"),
                BotCommand("bwh_on", "开启 BandwagonHost 补货通知"),
                BotCommand("bwh_off", "关闭 BandwagonHost 补货通知"),
                BotCommand("bwh_status", "查看 BandwagonHost 库存状态"),
                BotCommand("help", "查看帮助"),
            ]
        )
        assert application.job_queue is not None
        application.job_queue.run_repeating(
            monitor_job,
            interval=config.rss.poll_interval_seconds,
            first=1,
            name="rss-monitor",
        )
        if config.dmit.enabled:
            application.job_queue.run_repeating(
                dmit_monitor_job,
                interval=config.dmit.poll_interval_seconds,
                first=5,
                name="dmit-stock-monitor",
            )
        if config.bwh.enabled:
            application.job_queue.run_repeating(
                bwh_monitor_job,
                interval=config.bwh.poll_interval_seconds,
                first=10,
                name="bwh-stock-monitor",
            )
        application.job_queue.run_daily(cleanup_job, time=time(hour=3, tzinfo=UTC_PLUS_8))

    async def post_shutdown(application: Application) -> None:
        await fetcher.close()

    async def monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await service.check(context.bot)

    async def dmit_monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await dmit_service.check(context.bot)

    async def bwh_monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await bwh_service.check(context.bot)

    async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        sent, posts = storage.cleanup(config.database.retention_days)
        logger.info("历史数据清理完成：发送记录=%s 帖子=%s", sent, posts)

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("处理 Telegram 更新时发生异常", exc_info=context.error)

    application = (
        ApplicationBuilder()
        .token(config.telegram.token)
        .defaults(Defaults(tzinfo=UTC_PLUS_8))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(16)
        .connection_pool_size(32)
        .pool_timeout(10)
        .build()
    )
    application.bot_data.update(
        {
            "config": config,
            "storage": storage,
            "service": service,
            "dmit_service": dmit_service,
            "bwh_service": bwh_service,
        }
    )
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("add", handlers.add))
    application.add_handler(CommandHandler("remove", handlers.remove))
    application.add_handler(CommandHandler("list", handlers.list_keywords))
    application.add_handler(CommandHandler("clear", handlers.clear))
    application.add_handler(
        CallbackQueryHandler(handlers.clear_callback, pattern=r"^clear:(yes|no)$")
    )
    application.add_handler(CallbackQueryHandler(handlers.stock_callback, pattern=r"^stock:"))
    application.add_handler(CommandHandler("interval", handlers.interval))
    application.add_handler(CommandHandler("status", handlers.status))
    application.add_handler(CommandHandler("pause", handlers.pause))
    application.add_handler(CommandHandler("resume", handlers.resume))
    application.add_handler(CommandHandler("dmit_on", handlers.dmit_on))
    application.add_handler(CommandHandler("dmit_off", handlers.dmit_off))
    application.add_handler(CommandHandler("dmit_status", handlers.dmit_status))
    application.add_handler(CommandHandler("bwh_on", handlers.bwh_on))
    application.add_handler(CommandHandler("bwh_off", handlers.bwh_off))
    application.add_handler(CommandHandler("bwh_status", handlers.bwh_status))
    application.add_handler(CommandHandler("help", handlers.help))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(f"配置错误：{exc}") from exc
    configure_logging(config)
    logger.info("NodeSeek 监控机器人启动")
    build_application(config).run_polling(allowed_updates=Update.ALL_TYPES)
