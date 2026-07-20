"""Headless-browser plumbing shared by fetch and search.

Uses a headless Chromium context with cookies injected directly,
rather than a plain HTTP client — the design spike showed a plain
`requests` GET with the same cookies gets a 403 from Medium's
Cloudflare bot-detection (JS/TLS-fingerprint challenge), while a
headless Playwright context with the cookies injected via
`context.add_cookies(...)` gets a normal 200 with full content. See
docs/superpowers/specs/2026-07-14-mediumlm-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class PageResult:
    status: int
    final_url: str
    title: str
    html: str


def _to_playwright_cookies(cookies: List[dict]) -> List[dict]:
    return [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", False)),
            "httpOnly": False,
        }
        for c in cookies
    ]


class BrowserSession:
    """One headless browser reused across multiple fetches.

    Launching Chromium dominates per-article latency (~4-6s per
    launch); a batch of N articles through one session pays that cost
    once. A single page is reused across navigations — per-URL `goto`
    failures (timeout, DNS) leave the page navigable for the next URL.
    """

    def __init__(self, cookies: List[dict], settle_ms: int = 2000):
        self._cookies = cookies
        self._settle_ms = settle_ms
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            context = self._browser.new_context(user_agent=USER_AGENT)
            context.add_cookies(_to_playwright_cookies(self._cookies))
            self._page = context.new_page()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def fetch(self, url: str, settle_ms: Optional[int] = None) -> PageResult:
        """Load `url` in this session's page and return the settled result.

        Uses wait_until="load", not "networkidle" — Medium's page never
        goes fully network-idle (ongoing analytics/background requests),
        which caused "networkidle" to time out in the design spike.
        """
        wait = self._settle_ms if settle_ms is None else settle_ms
        response = self._page.goto(url, wait_until="load", timeout=45000)
        self._page.wait_for_timeout(wait)
        return PageResult(
            status=response.status if response else 0,
            final_url=self._page.url,
            title=self._page.title(),
            html=self._page.content(),
        )


def fetch_page(url: str, cookies: List[dict], settle_ms: int = 2000) -> PageResult:
    """One-shot fetch: a `BrowserSession` for a single URL."""
    with BrowserSession(cookies, settle_ms=settle_ms) as session:
        return session.fetch(url)
