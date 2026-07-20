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
    error: Optional[str] = None


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


def fetch_articles(urls: List[str], cookies: List[dict]) -> List[ArticleResult]:
    """Fetch several articles through one shared browser session.

    A failure on one URL is recorded as an `access: "error"` result
    (with the exception text in `error`) and the batch continues —
    partial failure is returned explicitly, never raised away or
    silently dropped. Results preserve input order.
    """
    results: List[ArticleResult] = []
    with browser_mod.BrowserSession(cookies) as session:
        for url in urls:
            try:
                page = session.fetch(url)
            except Exception as exc:
                results.append(
                    ArticleResult(
                        url=url,
                        title="",
                        access="error",
                        access_reason=None,
                        markdown="",
                        error=str(exc),
                    )
                )
                continue
            access, reason = parsing.detect_access(
                page.html, page.title, status=page.status
            )
            results.append(
                ArticleResult(
                    url=url,
                    title=page.title,
                    access=access,
                    access_reason=reason,
                    markdown=parsing.extract_article_markdown(page.html),
                )
            )
    return results
