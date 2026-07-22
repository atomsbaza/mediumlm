"""Search Medium via its own search page, driven through the same
headless-browser mechanism proven for fetch (see the design spec's
Open Questions — resolved section).

Unlike fetch, search deliberately runs unauthenticated: earlier live
testing showed Medium's search-results page populated via an async
GraphQL call that returned 403 for authenticated (cookied) requests
but succeeded for unauthenticated ones, likely due to stricter
bot/CSRF protection on privileged endpoints.

UPDATE (2026-07-19): as of this date, that GraphQL call is blocked
for headless traffic entirely — both authenticated and
unauthenticated requests to https://medium.com/_/graphql now return
403 (Cloudflare bot detection at the XHR level; longer settle times,
the chrome channel, and the firefox engine were all dead ends). The
search page itself still loads (HTTP 200), but it renders Medium's
own error state instead of results, and the only links left on the
page are sitewide footer links (Careers, Privacy, Rules, Terms) that
happen to match the article-slug regex. search() now detects that
error state and raises SearchUnavailableError rather than silently
returning those footer links as if they were results. Paywall/
membership resolution is unaffected — it still happens correctly
downstream, in fetch_article, which does use the real session."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup

from . import browser as browser_mod
from .urls import normalize_article_url

SEARCH_URL_TEMPLATE = "https://medium.com/search?q={query}"

# Marker text Medium's error state renders when the page's async
# GraphQL calls fail (e.g. blocked by bot detection) instead of
# populating with real search results.
SEARCH_ERROR_MARKER = "something went wrong on our end"

# Medium's search-results stream renders asynchronously after the
# initial page load (unlike article pages, which are server-rendered
# into the initial HTML), so it needs longer than browser.py's default
# settle_ms=2000 to populate with real results instead of just
# sitewide footer links. fetch_article and cookies.check_cookies don't
# need this extra wait, so it's set here rather than in browser.py.
SEARCH_SETTLE_MS = 6000

# Medium article URLs end in a dash followed by a lowercase-hex slug
# hash (e.g. "...-b9f433b82a5b"); this reliably distinguishes article
# links from nav/profile/search-again links on the results page. The
# boundary after the hash may be end-of-string, a path separator, a
# query string, or a fragment.
ARTICLE_HREF_RE = re.compile(r"-[0-9a-f]{12}(?=$|[/?#])")


class SearchUnavailableError(Exception):
    """Raised when Medium's search page loaded successfully but its
    results API was blocked, so no genuine results could be
    retrieved. This is distinct from a genuine zero-results search:
    it means search is broken right now, not that nothing was found."""


@dataclass
class SearchResult:
    title: str
    url: str


def parse_search_results(html: str) -> List[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not ARTICLE_HREF_RE.search(href):
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        url = normalize_article_url(href)
        # Site-chrome links (e.g. the footer's Careers link on
        # medium.com, or policy.medium.com's Privacy/Rules/Terms
        # links) can incidentally match the article-slug regex. Those
        # aren't real search results, so exclude anything that isn't
        # a medium.com article path.
        split = urlsplit(url)
        if split.netloc != "medium.com":
            continue
        if split.path.startswith("/jobs-at-medium/"):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append(SearchResult(title=title, url=url))
    return results


def search(query: str, cookies: List[dict], limit: int = 8) -> List[SearchResult]:
    """Search Medium for `query` and return candidate articles.

    Deliberately fetches the search page unauthenticated (ignores
    `cookies`) rather than with the caller's session. Live testing
    against real Medium showed search results are populated by an
    async GraphQL call that returns 403 for authenticated (cookied)
    requests — likely stricter bot/CSRF protection on privileged
    endpoints — while the identical request succeeds and returns real
    public results when unauthenticated. `cookies` is kept as a
    parameter for CLI signature compatibility, but intentionally not
    forwarded here. Paywall/membership resolution still happens
    correctly downstream in fetch_article, which does use the real
    session.

    Raises RuntimeError if the search page didn't load successfully
    (non-200 status) — this must not be silently reported as "zero
    results," which would be indistinguishable from a genuine empty
    search and is the same silent-failure class this project's error
    handling standards forbid.

    Raises SearchUnavailableError if the search page loaded (200) but
    rendered Medium's own error state instead of results — as of
    2026-07-19 this happens because Medium blocks the async GraphQL
    calls the results stream depends on for headless traffic
    entirely, regardless of authentication. That is also not the
    same as zero results, so it is not silently swallowed either: a
    caller catching this should fall back to WebSearch with
    `site:medium.com` and then `mediumlm fetch` each URL.
    """
    url = SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
    page = browser_mod.fetch_page(url, cookies=[], settle_ms=SEARCH_SETTLE_MS)
    if page.status != 200:
        raise RuntimeError(
            f"Medium search failed (status {page.status}) for query {query!r} — "
            "this is not the same as zero results; the search page did not load "
            "successfully"
        )
    results = parse_search_results(page.html)[:limit]
    if not results and SEARCH_ERROR_MARKER in page.html.lower():
        raise SearchUnavailableError(
            f"Medium blocked the search-results API for query {query!r} (the "
            "search page loaded but rendered Medium's error state instead of "
            "results) — fall back to WebSearch with 'site:medium.com "
            f"{query}' and then `mediumlm fetch` each URL"
        )
    return results
