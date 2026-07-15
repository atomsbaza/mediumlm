"""High-level article fetch: browser + parsing composed together."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import browser as browser_mod
from . import parsing


@dataclass
class ArticleResult:
    url: str
    title: str
    access: str
    access_reason: Optional[str]
    markdown: str


def fetch_article(url: str, cookies: List[dict]) -> ArticleResult:
    page = browser_mod.fetch_page(url, cookies)
    access, reason = parsing.detect_access(page.html, page.title, status=page.status)
    markdown = parsing.extract_article_markdown(page.html)
    return ArticleResult(
        url=url,
        title=page.title,
        access=access,
        access_reason=reason,
        markdown=markdown,
    )
