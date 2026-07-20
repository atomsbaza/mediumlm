from mediumlm import fetch, parsing


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


def test_fetch_article_flags_non_200_status_even_with_full_looking_body(monkeypatch):
    html = (
        "<html><head><title>Rate Limited</title></head>"
        "<body><article><h1>Looks Real</h1><p>"
        + ("word " * 150)
        + "</p></article></body></html>"
    )

    class FakePage:
        status = 429
        final_url = "https://medium.com/@a/test-piece-abc123abc123"
        title = "Rate Limited"

    FakePage.html = html

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = fetch.fetch_article("https://medium.com/@a/test-piece-abc123abc123", cookies=[])

    assert result.access == "preview"
    assert result.access_reason == "blocked"


class _FakePage:
    def __init__(self, url, title, html, status=200):
        self.final_url = url
        self.title = title
        self.html = html
        self.status = status


class _FakeSession:
    """Stands in for browser.BrowserSession: serves canned pages per URL,
    raises for URLs marked as failures."""

    def __init__(self, cookies, settle_ms=2000):
        self.pages = {}
        self.failures = {}
        self.enter_count = 0
        self.exit_raises = False

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.exit_raises:
            raise RuntimeError("teardown boom")
        return None

    def fetch(self, url, settle_ms=None):
        if url in self.failures:
            raise RuntimeError(self.failures[url])
        return self.pages[url]


def _full_article_html(heading):
    return (
        f"<html><head><title>{heading} – Medium</title></head>"
        f"<body><article><h1>{heading}</h1><p>"
        + ("word " * 150)
        + "</p></article></body></html>"
    )


def test_fetch_articles_uses_one_session_for_all_urls(monkeypatch):
    url_a = "https://medium.com/@a/first-abc123abc123"
    url_b = "https://medium.com/@a/second-def456def456"
    session = _FakeSession(cookies=[])
    session.pages = {
        url_a: _FakePage(url_a, "First – Medium", _full_article_html("First")),
        url_b: _FakePage(url_b, "Second – Medium", _full_article_html("Second")),
    }
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    results = fetch.fetch_articles([url_a, url_b], cookies=[])

    assert [r.url for r in results] == [url_a, url_b]
    assert all(r.access == "full" for r in results)
    assert all(r.error is None for r in results)
    assert "First" in results[0].markdown
    assert "Second" in results[1].markdown
    assert session.enter_count == 1


def test_fetch_articles_converts_per_url_failure_to_error_result(monkeypatch):
    url_ok = "https://medium.com/@a/works-abc123abc123"
    url_bad = "https://medium.com/@a/broken-def456def456"
    session = _FakeSession(cookies=[])
    session.pages = {
        url_ok: _FakePage(url_ok, "Works – Medium", _full_article_html("Works")),
    }
    session.failures = {url_bad: "net::ERR_NAME_NOT_RESOLVED"}
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    results = fetch.fetch_articles([url_bad, url_ok], cookies=[])

    assert results[0].url == url_bad
    assert results[0].access == "error"
    assert "ERR_NAME_NOT_RESOLVED" in results[0].error
    assert results[0].markdown == ""
    assert results[1].access == "full"
    assert results[1].error is None


def test_fetch_articles_isolates_parsing_failure_to_one_url(monkeypatch):
    url_ok = "https://medium.com/@a/works-abc123abc123"
    url_bad = "https://medium.com/@a/bad-parse-def456def456"
    marker = "BOOM_MARKER"
    session = _FakeSession(cookies=[])
    session.pages = {
        url_ok: _FakePage(url_ok, "Works – Medium", _full_article_html("Works")),
        url_bad: _FakePage(
            url_bad, "Bad – Medium", _full_article_html("Bad") + marker
        ),
    }
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    real_detect_access = parsing.detect_access

    def fake_detect_access(html, title, status=None):
        if marker in html:
            raise RuntimeError("boom")
        return real_detect_access(html, title, status=status)

    monkeypatch.setattr("mediumlm.parsing.detect_access", fake_detect_access)

    results = fetch.fetch_articles([url_bad, url_ok], cookies=[])

    assert results[0].url == url_bad
    assert results[0].access == "error"
    assert "boom" in results[0].error
    assert results[1].access == "full"
    assert results[1].error is None


def test_fetch_articles_returns_results_even_if_teardown_raises(monkeypatch):
    url_ok = "https://medium.com/@a/works-abc123abc123"
    session = _FakeSession(cookies=[])
    session.pages = {
        url_ok: _FakePage(url_ok, "Works – Medium", _full_article_html("Works")),
    }
    session.exit_raises = True
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    results = fetch.fetch_articles([url_ok], cookies=[])

    assert len(results) == 1
    assert results[0].url == url_ok
    assert results[0].access == "full"
    assert session.enter_count == 1
