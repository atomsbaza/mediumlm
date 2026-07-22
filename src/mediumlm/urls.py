"""Shared URL helpers."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit


def normalize_article_url(href: str) -> str:
    """Resolve a possibly-relative href to an absolute Medium URL with
    its query string (e.g. Medium's positional tracking param) and
    fragment stripped, so equivalent links dedupe and every result is
    directly fetchable by browser.fetch_page (which requires absolute
    URLs)."""
    absolute = urljoin("https://medium.com/", href)
    split = urlsplit(absolute)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))
