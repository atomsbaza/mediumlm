from pathlib import Path

import pytest

from mediumlm import search

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_search_results_filters_to_article_links():
    html = (FIXTURES / "search_results.html").read_text()
    results = search.parse_search_results(html)

    urls = [r.url for r in results]
    assert (
        "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b"
        in urls
    )
    # The plan's original assertion checked the raw relative href, which
    # encoded a bug (browser.fetch_page requires absolute URLs since
    # Playwright has no base_url configured). Deliberately updated to
    # expect the normalized absolute form.
    assert "https://medium.com/@janedoe/another-great-post-1a2b3c4d5e6f" in urls
    assert not any(u.endswith("/@janedoe") for u in urls)
    assert not any("signin" in u for u in urls)
    assert not any("search?q=" in u for u in urls)


def test_parse_search_results_dedupes_relative_and_absolute_with_tracking_params():
    html = """
    <div class="stream">
    <a href="/@janedoe/another-great-post-1a2b3c4d5e6f?source=search_post---------0">Another Great Post</a>
    <a href="https://medium.com/@janedoe/another-great-post-1a2b3c4d5e6f?source=search_post---------1">Another Great Post</a>
    </div>
    """
    results = search.parse_search_results(html)

    assert len(results) == 1
    assert results[0].url == "https://medium.com/@janedoe/another-great-post-1a2b3c4d5e6f"


def test_search_orchestration_applies_limit(monkeypatch):
    html = (FIXTURES / "search_results.html").read_text()

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"

    FakePage.html = html

    monkeypatch.setattr(
        "mediumlm.browser.fetch_page", lambda url, cookies, settle_ms=2000: FakePage()
    )

    results = search.search("mcp", cookies=[], limit=1)

    assert len(results) == 1


def test_search_ignores_caller_cookies_and_fetches_unauthenticated(monkeypatch):
    html = (FIXTURES / "search_results.html").read_text()
    captured_cookies = []

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"

    FakePage.html = html

    def fake_fetch_page(url, cookies, settle_ms=2000):
        captured_cookies.append(cookies)
        return FakePage()

    monkeypatch.setattr("mediumlm.browser.fetch_page", fake_fetch_page)

    search.search("mcp", cookies=[{"name": "sid", "value": "real-session-cookie"}], limit=8)

    assert captured_cookies == [[]]


def test_search_encodes_query_spaces_as_plus_not_percent20(monkeypatch):
    html = (FIXTURES / "search_results.html").read_text()
    captured_urls = []

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=claude+code+mcp"
        title = "claude code mcp - Medium Search"

    FakePage.html = html

    def fake_fetch_page(url, cookies, settle_ms=2000):
        captured_urls.append(url)
        return FakePage()

    monkeypatch.setattr("mediumlm.browser.fetch_page", fake_fetch_page)

    search.search("claude code mcp", cookies=[], limit=8)

    assert len(captured_urls) == 1
    assert "claude+code+mcp" in captured_urls[0]
    assert "claude%20code%20mcp" not in captured_urls[0]


def test_search_uses_longer_settle_time_than_browser_default(monkeypatch):
    html = (FIXTURES / "search_results.html").read_text()
    captured_settle_ms = []

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"

    FakePage.html = html

    def fake_fetch_page(url, cookies, settle_ms=2000):
        captured_settle_ms.append(settle_ms)
        return FakePage()

    monkeypatch.setattr("mediumlm.browser.fetch_page", fake_fetch_page)

    search.search("mcp", cookies=[], limit=8)

    assert len(captured_settle_ms) == 1
    assert captured_settle_ms[0] > 2000
    assert captured_settle_ms[0] == search.SEARCH_SETTLE_MS


def test_search_raises_on_non_200_status_instead_of_returning_empty(monkeypatch):
    class FakePage:
        status = 429
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"
        html = "<html><body>Rate limited</body></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies, settle_ms=6000: FakePage())

    with pytest.raises(RuntimeError):
        search.search("mcp", cookies=[], limit=8)


def test_parse_search_results_filters_footer_links_from_error_page():
    html = (FIXTURES / "search_error_page.html").read_text()
    results = search.parse_search_results(html)

    assert results == []


def test_search_raises_search_unavailable_on_error_page(monkeypatch):
    html = (FIXTURES / "search_error_page.html").read_text()

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"

    FakePage.html = html

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies, settle_ms=6000: FakePage())

    with pytest.raises(search.SearchUnavailableError, match="site:medium.com"):
        search.search("mcp", cookies=[], limit=8)


def test_search_returns_empty_list_when_no_results_and_no_error_marker(monkeypatch):
    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=asdkjhaskjdhaskjdh"
        title = "asdkjhaskjdhaskjdh - Medium Search"
        html = "<html><body><p>No stories match your search.</p></body></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies, settle_ms=6000: FakePage())

    results = search.search("asdkjhaskjdhaskjdh", cookies=[], limit=8)

    assert results == []
