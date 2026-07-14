"""Pure HTML parsing helpers — no network or browser involved, so these
run fast and deterministically in CI against saved fixtures."""
from __future__ import annotations

from typing import Optional, Tuple

from bs4 import BeautifulSoup
from markdownify import markdownify

BLOCKED_TITLE_MARKERS = ("just a moment", "attention required")
SIGNED_OUT_HREF_MARKERS = ("/m/signin", "/m/signup")
MEMBER_ONLY_MARKER = "member-only story"
FULL_ARTICLE_MIN_CHARS = 400


def detect_access(html: str, title: str) -> Tuple[str, Optional[str]]:
    """Classify a fetched page as full access or a specific block reason.

    Returns ("full", None) or ("preview", reason) where reason is one
    of "blocked", "cookies_expired", "not_member". These three collapse
    to the same visible symptom (short/no article text) but need
    different fixes, so they must not be conflated.
    """
    lowered_title = title.lower()
    if any(marker in lowered_title for marker in BLOCKED_TITLE_MARKERS):
        return "preview", "blocked"

    soup = BeautifulSoup(html, "html.parser")
    signed_out = any(
        marker in a.get("href", "")
        for marker in SIGNED_OUT_HREF_MARKERS
        for a in soup.find_all("a")
    )
    article = soup.find("article")
    article_text = article.get_text(" ", strip=True) if article else ""
    is_member_gated = MEMBER_ONLY_MARKER in soup.get_text(" ", strip=True).lower()

    if signed_out and len(article_text) < FULL_ARTICLE_MIN_CHARS:
        return "preview", "cookies_expired"
    if is_member_gated and len(article_text) < FULL_ARTICLE_MIN_CHARS:
        return "preview", "not_member"
    return "full", None


def extract_article_markdown(html: str) -> str:
    """Convert the <article> element's HTML to markdown, ignoring nav/
    footer chrome outside it. Falls back to the whole page if no
    <article> tag is present."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    target_html = str(article) if article else html
    return markdownify(target_html, heading_style="ATX").strip()
