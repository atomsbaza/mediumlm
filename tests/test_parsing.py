from pathlib import Path

from mediumlm import parsing

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_detect_access_full_article():
    html = _load("full_article.html")
    access, reason = parsing.detect_access(html, title="My Great Article – Medium")
    assert access == "full"
    assert reason is None


def test_detect_access_blocked_by_cloudflare():
    html = _load("blocked_cloudflare.html")
    access, reason = parsing.detect_access(html, title="Just a moment...")
    assert access == "preview"
    assert reason == "blocked"


def test_detect_access_cookies_expired():
    html = _load("signed_out_preview.html")
    access, reason = parsing.detect_access(html, title="Some Article – Medium")
    assert access == "preview"
    assert reason == "cookies_expired"


def test_detect_access_not_member():
    html = _load("not_member_preview.html")
    access, reason = parsing.detect_access(html, title="Member Story – Medium")
    assert access == "preview"
    assert reason == "not_member"


def test_detect_access_cookies_expired_with_absolute_signin_url():
    html = """
    <html>
    <head><title>Some Article – Medium</title></head>
    <body>
    <nav>
    <a href="https://medium.com/m/signin?operation=login">Sign in</a>
    </nav>
    <article>
    <h1>Some Article</h1>
    <p>Short preview text only, not the full story body.</p>
    </article>
    </body>
    </html>
    """
    access, reason = parsing.detect_access(html, title="Some Article – Medium")
    assert access == "preview"
    assert reason == "cookies_expired"


def test_detect_access_non_200_status_is_blocked_even_with_full_looking_body():
    html = _load("full_article.html")
    access, reason = parsing.detect_access(html, title="My Great Article – Medium", status=429)
    assert access == "preview"
    assert reason == "blocked"


def test_detect_access_status_none_preserves_existing_behavior():
    html = _load("full_article.html")
    access, reason = parsing.detect_access(html, title="My Great Article – Medium", status=None)
    assert access == "full"
    assert reason is None


def test_detect_access_empty_body_at_200_is_not_silently_full():
    html = "<html><head><title>Some Article – Medium</title></head><body></body></html>"
    access, reason = parsing.detect_access(html, title="Some Article – Medium", status=200)
    assert access == "preview"
    assert reason == "blocked"


def test_extract_article_markdown_pulls_article_body_only():
    html = _load("full_article.html")
    markdown = parsing.extract_article_markdown(html)
    assert "My Great Article" in markdown
    assert "Home" not in markdown  # nav link outside <article> must be excluded
    assert len(markdown) > 400
