"""Search Medium via its own search page, driven through the same
headless-browser mechanism proven for fetch (see the design spec's
Open Questions — resolved section).

Unlike fetch, search deliberately runs unauthenticated: live testing
showed Medium's search-results page populates via an async GraphQL
call that returns 403 for authenticated (cookied) requests but
succeeds for unauthenticated ones, likely due to stricter bot/CSRF
protection on privileged endpoints. Paywall/membership resolution
still happens correctly downstream, in fetch_article, which does use
the real session."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from . import browser as browser_mod

SEARCH_URL_TEMPLATE = "https://medium.com/search?q={query}"

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


@dataclass
class SearchResult:
    title: str
    url: str


def _normalize_article_url(href: str) -> str:
    """Resolve a possibly-relative href to an absolute Medium URL with
    its query string (e.g. Medium's positional tracking param) and
    fragment stripped, so equivalent links dedupe and every result is
    directly fetchable by browser.fetch_page (which requires absolute
    URLs)."""
    absolute = urljoin("https://medium.com/", href)
    split = urlsplit(absolute)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))


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
        url = _normalize_article_url(href)
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
    """
    url = SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
    page = browser_mod.fetch_page(url, cookies=[], settle_ms=SEARCH_SETTLE_MS)
    if page.status != 200:
        raise RuntimeError(
            f"Medium search failed (status {page.status}) for query {query!r} — "
            "this is not the same as zero results; the search page did not load "
            "successfully"
        )
    return parse_search_results(page.html)[:limit]
