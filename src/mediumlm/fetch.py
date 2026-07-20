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
    """Kept as the library-level single-article API (raises on failure);
    the CLI routes everything, including single URLs, through
    fetch_articles.
    """
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
    silently dropped. Results preserve input order. A teardown failure
    on the browser session (e.g. the browser crashed mid-batch) is
    suppressed so already-fetched results always reach the caller.
    """
    results: List[ArticleResult] = []
    session = browser_mod.BrowserSession(cookies)
    session.__enter__()
    try:
        for url in urls:
            try:
                page = session.fetch(url)
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
    finally:
        try:
            session.__exit__(None, None, None)
        except Exception:
            # Teardown failure must not discard already-fetched
            # results; the OS reaps the crashed browser process.
            pass
    return results
