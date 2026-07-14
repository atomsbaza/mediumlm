from mediumlm import fetch


def test_fetch_article_composes_access_and_markdown(monkeypatch):
    html = (
        "<html><head><title>Test Piece – Medium</title></head>"
        "<body><article><h1>Test Piece</h1><p>"
        + ("word " * 150)
        + "</p></article></body></html>"
    )

    class FakePage:
        status = 200
        final_url = "https://medium.com/@a/test-piece-abc123abc123"
        title = "Test Piece – Medium"

    FakePage.html = html

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = fetch.fetch_article("https://medium.com/@a/test-piece-abc123abc123", cookies=[])

    assert result.url == "https://medium.com/@a/test-piece-abc123abc123"
    assert result.access == "full"
    assert result.access_reason is None
    assert "Test Piece" in result.markdown


def test_fetch_article_flags_blocked_pages(monkeypatch):
    class FakePage:
        status = 403
        final_url = "https://medium.com/@a/test-piece-abc123abc123"
        title = "Just a moment..."
        html = "<html><body>Checking your browser. Cloudflare challenge.</body></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = fetch.fetch_article("https://medium.com/@a/test-piece-abc123abc123", cookies=[])

    assert result.access == "preview"
    assert result.access_reason == "blocked"
