"""High-level article fetch: browser + parsing composed together."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import List, Optional

from . import browser as browser_mod
from . import cache as cache_mod
from . import parsing


@dataclass
class ArticleResult:
    url: str
    title: str
    access: str
    access_reason: Optional[str]
    markdown: str
    error: Optional[str] = None
    cached: bool = False
    fetched_at: Optional[str] = None


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


def fetch_articles(
    urls: List[str],
    cookies: List[dict],
    use_cache: bool = True,
    cache_dir=None,
) -> List[ArticleResult]:
    """Fetch several articles, serving cache hits without a browser.

    The cache is consulted first (unless use_cache=False); a browser
    session is launched only when at least one URL misses. Full-access
    results are written back to the cache either way. Per-URL failures
    are recorded as `access: "error"` results and the batch continues.
    Teardown failures are suppressed so already-fetched results always
    reach the caller. Results preserve input order.
    """
    results: List[Optional[ArticleResult]] = [None] * len(urls)
    misses: List[int] = []
    for i, url in enumerate(urls):
        entry = cache_mod.load_cached(url, cache_dir=cache_dir) if use_cache else None
        if entry is not None:
            results[i] = ArticleResult(
                url=url,
                title=entry.get("title", ""),
                access="full",
                access_reason=None,
                markdown=entry.get("markdown", ""),
                cached=True,
                fetched_at=entry.get("fetched_at"),
            )
        else:
            misses.append(i)

    if misses:
        session = browser_mod.BrowserSession(cookies)
        session.__enter__()
        try:
            for i in misses:
                url = urls[i]
                try:
                    page = session.fetch(url)
                    access, reason = parsing.detect_access(
                        page.html, page.title, status=page.status
                    )
                    result = ArticleResult(
                        url=url,
                        title=page.title,
                        access=access,
                        access_reason=reason,
                        markdown=parsing.extract_article_markdown(page.html),
                    )
                except Exception as exc:
                    result = ArticleResult(
                        url=url,
                        title="",
                        access="error",
                        access_reason=None,
                        markdown="",
                        error=str(exc),
                    )
                results[i] = result
                cache_mod.store(dataclasses.asdict(result), cache_dir=cache_dir)
        finally:
            try:
                session.__exit__(None, None, None)
            except Exception:
                # Teardown failure must not discard already-fetched
                # results; the OS reaps the crashed browser process.
                pass
    return [r for r in results if r is not None]
