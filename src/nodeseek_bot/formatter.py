from __future__ import annotations

import html
import re

from .models import UTC_PLUS_8, Post

CATEGORY_NAMES = {
    "daily": "日常",
    "tech": "技术",
    "info": "情报",
    "review": "测评",
    "trade": "交易",
    "carpool": "拼车",
    "promotion": "推广",
    "promo": "推广",
}


def display_category(category: str) -> str:
    parts = [part.strip() for part in category.split("/")]
    return " / ".join(CATEGORY_NAMES.get(part.casefold(), part) for part in parts)


def highlight_title(title: str, keywords: list[str]) -> str:
    cleaned = sorted({word for word in keywords if word}, key=len, reverse=True)
    if not cleaned:
        return html.escape(title)
    pattern = re.compile("|".join(re.escape(word) for word in cleaned), re.IGNORECASE)
    parts: list[str] = []
    offset = 0
    for match in pattern.finditer(title):
        parts.append(html.escape(title[offset : match.start()]))
        parts.append(f"<b>{html.escape(match.group(0))}</b>")
        offset = match.end()
    parts.append(html.escape(title[offset:]))
    return "".join(parts)


def format_post(post: Post, matched_keywords: list[str]) -> str:
    published = (
        post.published_at.astimezone(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M UTC+8")
        if post.published_at
        else "未知"
    )
    summary = post.summary[:200]
    if len(post.summary) > 200:
        summary += "…"
    lines = [
        f"🔔 {highlight_title(post.title, matched_keywords)}",
        "",
        f"📂 板块：{html.escape(display_category(post.category))}",
        f"👤 作者：{html.escape(post.author)}",
        f"🕒 时间：{published}",
    ]
    if summary:
        lines.extend(["", html.escape(summary)])
    lines.extend(["", f"🎯 命中：{html.escape('、'.join(matched_keywords))}"])
    return "\n".join(lines)
