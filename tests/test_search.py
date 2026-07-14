from pathlib import Path

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
    assert "/@janedoe/another-great-post-1a2b3c4d5e6f" in urls
    assert not any(u.endswith("/@janedoe") for u in urls)
    assert not any("signin" in u for u in urls)
    assert not any("search?q=" in u for u in urls)


def test_search_orchestration_applies_limit(monkeypatch):
    html = (FIXTURES / "search_results.html").read_text()

    class FakePage:
        status = 200
        final_url = "https://medium.com/search?q=mcp"
        title = "mcp - Medium Search"

    FakePage.html = html

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    results = search.search("mcp", cookies=[], limit=1)

    assert len(results) == 1
