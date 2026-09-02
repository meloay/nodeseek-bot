from __future__ import annotations

from .models import Keyword, Post


def match_post(post: Post, keywords: list[Keyword], scope: str = "title") -> list[str]:
    text = post.title if scope == "title" else f"{post.title}\n{post.summary}"
    folded = text.casefold()
    matched: list[str] = []
    seen: set[str] = set()

    for item in keywords:
        if item.is_exclude:
            continue
        needle = item.keyword.strip()
        if not needle:
            continue
        key = needle.casefold()
        if key in folded and key not in seen:
            seen.add(key)
            matched.append(needle)
    return matched
