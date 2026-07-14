"""Search Medium via its own search page, driven through the same
headless-browser mechanism proven for fetch (see the design spec's
Open Questions — resolved section)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from . import browser as browser_mod

SEARCH_URL_TEMPLATE = "https://medium.com/search?q={query}"

# Medium article URLs end in a dash followed by a lowercase-hex slug
# hash (e.g. "...-b9f433b82a5b"); this reliably distinguishes article
# links from nav/profile/search-again links on the results page.
ARTICLE_HREF_RE = re.compile(r"-[0-9a-f]{12}(?:\?.*)?$")


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
        if not title or href in seen:
            continue
        seen.add(href)
        results.append(SearchResult(title=title, url=href))
    return results


def search(query: str, cookies: List[dict], limit: int = 8) -> List[SearchResult]:
    url = SEARCH_URL_TEMPLATE.format(query=quote(query))
    page = browser_mod.fetch_page(url, cookies)
    return parse_search_results(page.html)[:limit]
