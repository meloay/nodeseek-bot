from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import (
    BwhProduct,
    BwhStockEvent,
    DmitProduct,
    DmitStockEvent,
    Keyword,
    Post,
    User,
    utc_now,
)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Storage:
    def __init__(self, path: str | Path, default_interval: int = 5) -> None:
        self.path = Path(path)
        self.default_interval = default_interval

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    chat_type TEXT NOT NULL DEFAULT 'private',
                    chat_title TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    check_interval INTEGER NOT NULL DEFAULT 5 CHECK (check_interval > 0),
                    match_scope TEXT NOT NULL DEFAULT 'title'
                        CHECK (match_scope IN ('title', 'full')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivery_since TEXT NOT NULL,
                    last_checked_at TEXT,
                    dmit_stock_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK (dmit_stock_enabled IN (0, 1)),
                    dmit_enabled_since TEXT,
                    bwh_stock_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK (bwh_stock_enabled IN (0, 1)),
                    bwh_enabled_since TEXT
                );

                CREATE TABLE IF NOT EXISTS keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    keyword TEXT NOT NULL COLLATE NOCASE,
                    match_mode TEXT NOT NULL DEFAULT 'fuzzy'
                        CHECK (match_mode IN ('exact', 'fuzzy', 'regex')),
                    is_exclude INTEGER NOT NULL DEFAULT 0 CHECK (is_exclude IN (0, 1)),
                    created_at TEXT NOT NULL,
                    UNIQUE (user_id, keyword, match_mode, is_exclude)
                );

                CREATE TABLE IF NOT EXISTS category_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    category TEXT NOT NULL COLLATE NOCASE,
                    UNIQUE (user_id, category)
                );

                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    author TEXT NOT NULL,
                    category TEXT NOT NULL,
                    published_at TEXT,
                    summary TEXT NOT NULL,
                    discovered_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sent_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
                    post_title TEXT NOT NULL,
                    matched_keywords TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE (user_id, post_id)
                );

                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dmit_products (
                    product_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    network TEXT NOT NULL,
                    hardware TEXT NOT NULL,
                    specs TEXT NOT NULL,
                    price TEXT NOT NULL,
                    is_available INTEGER NOT NULL CHECK (is_available IN (0, 1)),
                    order_url TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dmit_stock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    network TEXT NOT NULL,
                    hardware TEXT NOT NULL,
                    specs TEXT NOT NULL,
                    price TEXT NOT NULL,
                    order_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dmit_notifications (
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL REFERENCES dmit_stock_events(id) ON DELETE CASCADE,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS bwh_products (
                    product_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tiers TEXT NOT NULL,
                    datacenters TEXT NOT NULL,
                    specs TEXT NOT NULL,
                    price TEXT NOT NULL,
                    is_available INTEGER NOT NULL CHECK (is_available IN (0, 1)),
                    order_url TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bwh_stock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    tiers TEXT NOT NULL,
                    datacenters TEXT NOT NULL,
                    specs TEXT NOT NULL,
                    price TEXT NOT NULL,
                    order_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bwh_notifications (
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL REFERENCES bwh_stock_events(id) ON DELETE CASCADE,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_keywords_user ON keywords(user_id);
                CREATE INDEX IF NOT EXISTS idx_posts_discovered ON posts(discovered_at);
                CREATE INDEX IF NOT EXISTS idx_sent_posts_user_time
                    ON sent_posts(user_id, sent_at);
                CREATE INDEX IF NOT EXISTS idx_dmit_events_created
                    ON dmit_stock_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_bwh_events_created
                    ON bwh_stock_events(created_at);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "dmit_stock_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN dmit_stock_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "dmit_enabled_since" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN dmit_enabled_since TEXT")
            if "bwh_stock_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN bwh_stock_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "bwh_enabled_since" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN bwh_enabled_since TEXT")

            if "chat_type" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN chat_type TEXT NOT NULL DEFAULT 'private'"
                )
            if "chat_title" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN chat_title TEXT")

    def ensure_user(
        self,
        user_id: int,
        username: str | None,
        chat_type: str = "private",
        chat_title: str | None = None,
    ) -> User:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, chat_type, chat_title,
                    is_active, check_interval, match_scope,
                    created_at, updated_at, delivery_since
                ) VALUES (?, ?, ?, ?, 1, ?, 'title', ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    chat_type = excluded.chat_type,
                    chat_title = excluded.chat_title,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    username,
                    chat_type,
                    chat_title,
                    self.default_interval,
                    _iso(now),
                    _iso(now),
                    _iso(now),
                ),
            )
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: int) -> User | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return self._user_from_row(row) if row else None

    def set_active(self, user_id: int, active: bool) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET is_active = ?, updated_at = ?,
                    delivery_since = CASE WHEN ? = 1 THEN ? ELSE delivery_since END,
                    last_checked_at = CASE WHEN ? = 1 THEN NULL ELSE last_checked_at END
                WHERE user_id = ?
                """,
                (int(active), _iso(now), int(active), _iso(now), int(active), user_id),
            )

    def set_interval(self, user_id: int, minutes: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET check_interval = ?, updated_at = ? WHERE user_id = ?",
                (minutes, _iso(utc_now()), user_id),
            )

    def set_dmit_enabled(self, user_id: int, enabled: bool) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET dmit_stock_enabled = ?,
                    dmit_enabled_since = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (int(enabled), int(enabled), _iso(now), _iso(now), user_id),
            )

    def list_dmit_subscribers(self) -> list[User]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM users
                WHERE is_active = 1 AND dmit_stock_enabled = 1
                ORDER BY user_id
                """
            ).fetchall()
        return [self._user_from_row(row) for row in rows]

    def set_bwh_enabled(self, user_id: int, enabled: bool) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET bwh_stock_enabled = ?,
                    bwh_enabled_since = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (int(enabled), int(enabled), _iso(now), _iso(now), user_id),
            )

    def list_bwh_subscribers(self) -> list[User]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM users
                WHERE is_active = 1 AND bwh_stock_enabled = 1
                ORDER BY user_id
                """
            ).fetchall()
        return [self._user_from_row(row) for row in rows]

    def mark_checked(self, user_id: int, checked_at: datetime | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET last_checked_at = ?, updated_at = ? WHERE user_id = ?",
                (_iso(checked_at or utc_now()), _iso(utc_now()), user_id),
            )

    def reset_delivery_window_for_all(self, since: datetime | None = None) -> None:
        now = since or utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET delivery_since = ?, last_checked_at = ?, updated_at = ?
                """,
                (_iso(now), _iso(now), _iso(now)),
            )

    def list_due_users(self, now: datetime | None = None) -> list[User]:
        current = now or utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users WHERE is_active = 1 ORDER BY user_id"
            ).fetchall()
        users = [self._user_from_row(row) for row in rows]
        return [
            user
            for user in users
            if user.last_checked_at is None
            or user.last_checked_at + timedelta(minutes=user.check_interval) <= current
        ]

    def add_keyword(
        self,
        user_id: int,
        keyword: str,
        match_mode: str = "fuzzy",
        is_exclude: bool = False,
    ) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO keywords (user_id, keyword, match_mode, is_exclude, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, keyword, match_mode, int(is_exclude), _iso(utc_now())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_keyword(self, user_id: int, keyword: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM keywords WHERE user_id = ? AND keyword = ? AND is_exclude = 0",
                (user_id, keyword),
            )
        return cursor.rowcount > 0

    def clear_keywords(self, user_id: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM keywords WHERE user_id = ?", (user_id,))
        return cursor.rowcount

    def list_keywords(self, user_id: int, include_excluded: bool = False) -> list[Keyword]:
        query = "SELECT * FROM keywords WHERE user_id = ?"
        if not include_excluded:
            query += " AND is_exclude = 0"
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, (user_id,)).fetchall()
        return [
            Keyword(
                id=row["id"],
                user_id=row["user_id"],
                keyword=row["keyword"],
                match_mode=row["match_mode"],
                is_exclude=bool(row["is_exclude"]),
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    def save_posts(self, posts: Iterable[Post], discovered_at: datetime | None = None) -> int:
        now = discovered_at or utc_now()
        inserted = 0
        with self._connect() as connection:
            for post in posts:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO posts (
                        post_id, title, link, author, category, published_at, summary, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        post.post_id,
                        post.title,
                        post.link,
                        post.author,
                        post.category,
                        _iso(post.published_at),
                        post.summary,
                        _iso(now),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def list_unsent_posts(self, user: User, limit: int = 100) -> list[Post]:
        threshold = max(
            value for value in (user.delivery_since, user.last_checked_at) if value is not None
        )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.* FROM posts p
                LEFT JOIN sent_posts s
                    ON s.post_id = p.post_id AND s.user_id = ?
                WHERE s.id IS NULL AND p.discovered_at > ?
                ORDER BY p.discovered_at, p.post_id
                LIMIT ?
                """,
                (user.user_id, _iso(threshold), limit),
            ).fetchall()
        return [
            Post(
                post_id=row["post_id"],
                title=row["title"],
                link=row["link"],
                author=row["author"],
                category=row["category"],
                published_at=_dt(row["published_at"]),
                summary=row["summary"],
            )
            for row in rows
        ]

    def record_sent(self, user_id: int, post: Post, matched_keywords: list[str]) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO sent_posts (
                        user_id, post_id, post_title, matched_keywords, sent_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        post.post_id,
                        post.title,
                        json.dumps(matched_keywords, ensure_ascii=False),
                        _iso(utc_now()),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_state(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM system_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, _iso(utc_now())),
            )

    def sync_dmit_products(
        self, products: Iterable[DmitProduct], checked_at: datetime | None = None
    ) -> int:
        now = checked_at or utc_now()
        product_list = list(products)
        created_events = 0
        with self._connect() as connection:
            baseline = connection.execute("SELECT COUNT(*) FROM dmit_products").fetchone()[0] == 0
            for product in product_list:
                existing = connection.execute(
                    "SELECT is_available FROM dmit_products WHERE product_key = ?",
                    (product.product_key,),
                ).fetchone()
                became_available = product.is_available and (
                    existing is None or not bool(existing["is_available"])
                )
                connection.execute(
                    """
                    INSERT INTO dmit_products (
                        product_key, name, location, network, hardware, specs, price,
                        is_available, order_url, first_seen_at, last_seen_at, last_changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_key) DO UPDATE SET
                        name = excluded.name,
                        location = excluded.location,
                        network = excluded.network,
                        hardware = excluded.hardware,
                        specs = excluded.specs,
                        price = excluded.price,
                        is_available = excluded.is_available,
                        order_url = excluded.order_url,
                        last_seen_at = excluded.last_seen_at,
                        last_changed_at = CASE
                            WHEN dmit_products.is_available != excluded.is_available
                            THEN excluded.last_changed_at
                            ELSE dmit_products.last_changed_at
                        END
                    """,
                    (
                        product.product_key,
                        product.name,
                        product.location,
                        product.network,
                        product.hardware,
                        json.dumps(product.specs, ensure_ascii=False),
                        product.price,
                        int(product.is_available),
                        product.order_url,
                        _iso(now),
                        _iso(now),
                        _iso(now),
                    ),
                )
                if became_available and not baseline and product.order_url:
                    connection.execute(
                        """
                        INSERT INTO dmit_stock_events (
                            product_key, name, location, network, hardware, specs,
                            price, order_url, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            product.product_key,
                            product.name,
                            product.location,
                            product.network,
                            product.hardware,
                            json.dumps(product.specs, ensure_ascii=False),
                            product.price,
                            product.order_url,
                            _iso(now),
                        ),
                    )
                    created_events += 1

            seen_keys = {product.product_key for product in product_list}
            available_rows = connection.execute(
                "SELECT product_key FROM dmit_products WHERE is_available = 1"
            ).fetchall()
            missing = [
                row["product_key"] for row in available_rows if row["product_key"] not in seen_keys
            ]
            if missing:
                connection.executemany(
                    """
                    UPDATE dmit_products
                    SET is_available = 0, order_url = NULL, last_changed_at = ?
                    WHERE product_key = ?
                    """,
                    [(_iso(now), key) for key in missing],
                )
        return created_events

    def list_unsent_dmit_events(self, user: User, limit: int = 50) -> list[DmitStockEvent]:
        if not user.dmit_enabled_since:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.* FROM dmit_stock_events e
                LEFT JOIN dmit_notifications n
                    ON n.event_id = e.id AND n.user_id = ?
                WHERE n.event_id IS NULL AND e.created_at >= ?
                ORDER BY e.created_at, e.id
                LIMIT ?
                """,
                (user.user_id, _iso(user.dmit_enabled_since), limit),
            ).fetchall()
        return [
            DmitStockEvent(
                id=row["id"],
                product_key=row["product_key"],
                name=row["name"],
                location=row["location"],
                network=row["network"],
                hardware=row["hardware"],
                specs=tuple(json.loads(row["specs"])),
                price=row["price"],
                order_url=row["order_url"],
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    def record_dmit_notification(self, user_id: int, event_id: int) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO dmit_notifications (user_id, event_id, sent_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, event_id, _iso(utc_now())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def dmit_stock_counts(self) -> tuple[int, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN is_available = 1 THEN 1 ELSE 0 END) AS available,
                    SUM(CASE WHEN is_available = 0 THEN 1 ELSE 0 END) AS unavailable
                FROM dmit_products
                WHERE last_seen_at = (SELECT MAX(last_seen_at) FROM dmit_products)
                """
            ).fetchone()
        return int(row["available"] or 0), int(row["unavailable"] or 0)

    def list_available_dmit_products(self) -> list[DmitProduct]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM dmit_products
                WHERE is_available = 1 AND order_url IS NOT NULL
                ORDER BY location, network, hardware, name
                """
            ).fetchall()
        return [
            DmitProduct(
                product_key=row["product_key"],
                name=row["name"],
                location=row["location"],
                network=row["network"],
                hardware=row["hardware"],
                specs=tuple(json.loads(row["specs"])),
                price=row["price"],
                is_available=True,
                order_url=row["order_url"],
            )
            for row in rows
        ]

    def sync_bwh_products(
        self, products: Iterable[BwhProduct], checked_at: datetime | None = None
    ) -> int:
        now = checked_at or utc_now()
        product_list = list(products)
        created_events = 0
        with self._connect() as connection:
            baseline = connection.execute("SELECT COUNT(*) FROM bwh_products").fetchone()[0] == 0
            for product in product_list:
                existing = connection.execute(
                    "SELECT is_available FROM bwh_products WHERE product_key = ?",
                    (product.product_key,),
                ).fetchone()
                became_available = product.is_available and (
                    existing is None or not bool(existing["is_available"])
                )
                connection.execute(
                    """
                    INSERT INTO bwh_products (
                        product_key, name, tiers, datacenters, specs, price,
                        is_available, order_url, first_seen_at, last_seen_at,
                        last_changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_key) DO UPDATE SET
                        name = excluded.name,
                        tiers = excluded.tiers,
                        datacenters = excluded.datacenters,
                        specs = excluded.specs,
                        price = excluded.price,
                        is_available = excluded.is_available,
                        order_url = excluded.order_url,
                        last_seen_at = excluded.last_seen_at,
                        last_changed_at = CASE
                            WHEN bwh_products.is_available != excluded.is_available
                            THEN excluded.last_changed_at
                            ELSE bwh_products.last_changed_at
                        END
                    """,
                    (
                        product.product_key,
                        product.name,
                        json.dumps(product.tiers, ensure_ascii=False),
                        json.dumps(product.datacenters, ensure_ascii=False),
                        json.dumps(product.specs, ensure_ascii=False),
                        product.price,
                        int(product.is_available),
                        product.order_url,
                        _iso(now),
                        _iso(now),
                        _iso(now),
                    ),
                )
                if became_available and not baseline and product.order_url:
                    connection.execute(
                        """
                        INSERT INTO bwh_stock_events (
                            product_key, name, tiers, datacenters, specs,
                            price, order_url, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            product.product_key,
                            product.name,
                            json.dumps(product.tiers, ensure_ascii=False),
                            json.dumps(product.datacenters, ensure_ascii=False),
                            json.dumps(product.specs, ensure_ascii=False),
                            product.price,
                            product.order_url,
                            _iso(now),
                        ),
                    )
                    created_events += 1

            seen_keys = {product.product_key for product in product_list}
            available_rows = connection.execute(
                "SELECT product_key FROM bwh_products WHERE is_available = 1"
            ).fetchall()
            missing = [
                row["product_key"] for row in available_rows if row["product_key"] not in seen_keys
            ]
            if missing:
                connection.executemany(
                    """
                    UPDATE bwh_products
                    SET is_available = 0, order_url = NULL, last_changed_at = ?
                    WHERE product_key = ?
                    """,
                    [(_iso(now), key) for key in missing],
                )
        return created_events

    def list_unsent_bwh_events(self, user: User, limit: int = 50) -> list[BwhStockEvent]:
        if not user.bwh_enabled_since:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.* FROM bwh_stock_events e
                LEFT JOIN bwh_notifications n
                    ON n.event_id = e.id AND n.user_id = ?
                WHERE n.event_id IS NULL AND e.created_at >= ?
                ORDER BY e.created_at, e.id
                LIMIT ?
                """,
                (user.user_id, _iso(user.bwh_enabled_since), limit),
            ).fetchall()
        return [
            BwhStockEvent(
                id=row["id"],
                product_key=row["product_key"],
                name=row["name"],
                tiers=tuple(json.loads(row["tiers"])),
                datacenters=tuple(json.loads(row["datacenters"])),
                specs=tuple(json.loads(row["specs"])),
                price=row["price"],
                order_url=row["order_url"],
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    def record_bwh_notification(self, user_id: int, event_id: int) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO bwh_notifications (user_id, event_id, sent_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, event_id, _iso(utc_now())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def bwh_stock_counts(self) -> tuple[int, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN is_available = 1 THEN 1 ELSE 0 END) AS available,
                    SUM(CASE WHEN is_available = 0 THEN 1 ELSE 0 END) AS unavailable
                FROM bwh_products
                """
            ).fetchone()
        return int(row["available"] or 0), int(row["unavailable"] or 0)

    def list_available_bwh_products(self) -> list[BwhProduct]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM bwh_products
                WHERE is_available = 1 AND order_url IS NOT NULL
                ORDER BY CAST(product_key AS INTEGER), name
                """
            ).fetchall()
        return [
            BwhProduct(
                product_key=row["product_key"],
                name=row["name"],
                tiers=tuple(json.loads(row["tiers"])),
                datacenters=tuple(json.loads(row["datacenters"])),
                specs=tuple(json.loads(row["specs"])),
                price=row["price"],
                is_available=True,
                order_url=row["order_url"],
            )
            for row in rows
        ]

    def cleanup(self, retention_days: int) -> tuple[int, int]:
        threshold = _iso(utc_now() - timedelta(days=retention_days))
        with self._connect() as connection:
            sent = connection.execute(
                "DELETE FROM sent_posts WHERE sent_at < ?", (threshold,)
            ).rowcount
            posts = connection.execute(
                "DELETE FROM posts WHERE discovered_at < ?", (threshold,)
            ).rowcount
        return sent, posts

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> User:
        created_at = _dt(row["created_at"])
        updated_at = _dt(row["updated_at"])
        delivery_since = _dt(row["delivery_since"])
        assert created_at and updated_at and delivery_since
        return User(
            user_id=row["user_id"],
            username=row["username"],
            chat_type=row["chat_type"],
            chat_title=row["chat_title"],
            is_active=bool(row["is_active"]),
            check_interval=row["check_interval"],
            match_scope=row["match_scope"],
            created_at=created_at,
            updated_at=updated_at,
            delivery_since=delivery_since,
            last_checked_at=_dt(row["last_checked_at"]),
            dmit_stock_enabled=bool(row["dmit_stock_enabled"]),
            dmit_enabled_since=_dt(row["dmit_enabled_since"]),
            bwh_stock_enabled=bool(row["bwh_stock_enabled"]),
            bwh_enabled_since=_dt(row["bwh_enabled_since"]),
        )
