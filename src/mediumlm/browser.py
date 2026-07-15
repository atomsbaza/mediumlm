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
from typing import List

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


def fetch_page(url: str, cookies: List[dict], settle_ms: int = 2000) -> PageResult:
    """Load `url` in a headless browser with `cookies` injected.

    Uses wait_until="load", not "networkidle" — Medium's page never
    goes fully network-idle (ongoing analytics/background requests),
    which caused "networkidle" to time out in the design spike.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            context.add_cookies(_to_playwright_cookies(cookies))
            page = context.new_page()
            response = page.goto(url, wait_until="load", timeout=45000)
            page.wait_for_timeout(settle_ms)
            return PageResult(
                status=response.status if response else 0,
                final_url=page.url,
                title=page.title(),
                html=page.content(),
            )
        finally:
            browser.close()
