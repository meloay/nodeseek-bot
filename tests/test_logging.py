import logging
from datetime import datetime, timezone

from nodeseek_bot.app import UtcPlus8Formatter


def test_log_formatter_uses_utc_plus_8() -> None:
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    record.created = datetime(2026, 8, 28, tzinfo=timezone.utc).timestamp()
    formatter = UtcPlus8Formatter("%(asctime)s %(message)s")
    assert formatter.format(record) == "2026-08-28T08:00:00+0800 hello"
