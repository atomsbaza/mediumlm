# mediumlm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `mediumlm` Python CLI and its Claude Code skill wrapper so a topic can be researched on Medium using the user's own logged-in session, producing a chat summary, a saved research note, and (on request) NotebookLM artifacts.

**Architecture:** A `src/`-layout Python package (`mediumlm`) with small, single-responsibility modules — `browser.py` (shared headless Playwright fetch, the mechanism proven in the design spike), `cookies.py` (session storage, built on top of `browser.py` for its session-check), `parsing.py` (pure HTML→markdown and access-detection logic, fully unit-testable without a browser), `fetch.py` and `search.py` (orchestration on top of `browser.py` + `parsing.py`), and `cli.py` (argparse entry point). A thin `SKILL.md` at `~/.claude/skills/mediumlm/` tells Claude how to drive the installed CLI; no logic lives in the skill directory itself. Search is implemented by driving Medium's own search page through the same headless-browser mechanism already proven for `fetch` (see spec's Open Questions) — not a second GraphQL/WebSearch code path, since there's no evidence yet that the browser-driven approach won't work for search too. If it turns out fragile once used for real, the spec's documented `WebSearch` fallback remains available as a manual escape hatch for Claude to reach for, without having built and maintained a second implementation speculatively.

**Tech Stack:** Python 3.9+, Playwright (headless Chromium), `browser_cookie3` (Chrome cookie extraction), BeautifulSoup4 + `markdownify` (HTML parsing/conversion), pytest.

**Reference:** `docs/superpowers/specs/2026-07-14-mediumlm-design.md` — read this first. In particular, the "Open Questions — resolved" section documents the two spikes already run (raw-HTTP fetch failed with a Cloudflare 403; headless Playwright with injected cookies succeeded with a 200 and full article text). This plan implements the Playwright-based mechanism, not the raw-HTTP one described earlier in the spec's Components section.

**Module build order matters:** `browser.py` is built before `cookies.py` because `cookies.py`'s session-check (`check_cookies`) calls into `browser.py` — building it first means that dependency exists when its tests are written, instead of monkeypatching a module that doesn't exist yet.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/mediumlm/__init__.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create the package skeleton**

```bash
mkdir -p /Users/pisitkoolplukpol/Work/mediumlm/src/mediumlm
mkdir -p /Users/pisitkoolplukpol/Work/mediumlm/tests/fixtures
touch /Users/pisitkoolplukpol/Work/mediumlm/src/mediumlm/__init__.py
touch /Users/pisitkoolplukpol/Work/mediumlm/tests/fixtures/.gitkeep
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "mediumlm"
version = "0.1.0"
description = "Research Medium topics using your own logged-in Medium session"
requires-python = ">=3.9"
dependencies = [
    "browser_cookie3",
    "playwright",
    "beautifulsoup4",
    "markdownify",
]

[project.optional-dependencies]
dev = ["pytest"]

[project.scripts]
mediumlm = "mediumlm.cli:main"

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 3: Editable-install the package and its dev dependencies**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && pip3 install -e ".[dev]"`
Expected: installs successfully, ending with `Successfully installed mediumlm-0.1.0` (plus its dependencies — some may already be satisfied from the earlier spike in this session).

- [ ] **Step 4: Install the Playwright Chromium browser (skip if already installed)**

Run: `python3 -m playwright install chromium`
Expected: either downloads Chromium, or prints that it's already installed. (Already done once earlier in this session — should be a no-op.)

- [ ] **Step 5: Verify pytest can collect the (currently empty) test suite**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/ -v`
Expected: `no tests ran` (or similar) with exit code `0` or `5` — no import errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add pyproject.toml src/mediumlm/__init__.py tests/fixtures/.gitkeep
git commit -m "chore: scaffold mediumlm Python package"
```

---

## Task 2: Shared headless browser fetch (`browser.py`)

**Files:**
- Create: `src/mediumlm/browser.py`
- Test: `tests/test_browser.py`

This is the mechanism proven in the design spike (headless Playwright + injected cookies, `wait_until="load"` not `"networkidle"`). It's tested against a local HTTP server rather than live Medium, so the test is fast, deterministic, and doesn't depend on a third-party site or your account — the thing being verified here is "does cookie injection actually reach the request," which a local server can prove just as well as Medium can. This module is built first because `cookies.py`'s session-check depends on it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browser.py
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from mediumlm import browser


class _EchoCookieHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        cookie_header = self.headers.get("Cookie", "no-cookie")
        body = (
            f"<html><head><title>echo</title></head>"
            f"<body>{cookie_header}</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence default per-request stderr logging


def test_fetch_page_injects_cookies_into_the_request():
    server = HTTPServer(("127.0.0.1", 0), _EchoCookieHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser.fetch_page(
            f"http://127.0.0.1:{port}/",
            cookies=[
                {
                    "name": "probe",
                    "value": "hello123",
                    "domain": "127.0.0.1",
                    "path": "/",
                    "secure": False,
                }
            ],
        )
        assert result.status == 200
        assert "hello123" in result.html
        assert result.title == "echo"
    finally:
        server.shutdown()
        thread.join()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_browser.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.browser'`.

- [ ] **Step 3: Implement `browser.py`**

```python
# src/mediumlm/browser.py
"""Headless-browser plumbing shared by fetch and search.

Uses a headless Chromium context with cookies injected directly,
rather than a plain HTTP client — the design spike showed a plain
`requests` GET with the same cookies gets a 403 from Medium's
Cloudflare bot-detection (JS/TLS-fingerprint challenge), while a
headless Playwright context with the cookies injected via
`context.add_cookies(...)` gets a normal 200 with full content. See
docs/superpowers/specs/2026-07-14-mediumlm-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class PageResult:
    status: int
    final_url: str
    title: str
    html: str


def _to_playwright_cookies(cookies: List[dict]) -> List[dict]:
    return [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", False)),
            "httpOnly": False,
        }
        for c in cookies
    ]


def fetch_page(url: str, cookies: List[dict], settle_ms: int = 2000) -> PageResult:
    """Load `url` in a headless browser with `cookies` injected.

    Uses wait_until="load", not "networkidle" — Medium's page never
    goes fully network-idle (ongoing analytics/background requests),
    which caused "networkidle" to time out in the design spike.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            context.add_cookies(_to_playwright_cookies(cookies))
            page = context.new_page()
            response = page.goto(url, wait_until="load", timeout=45000)
            page.wait_for_timeout(settle_ms)
            return PageResult(
                status=response.status if response else 0,
                final_url=page.url,
                title=page.title(),
                html=page.content(),
            )
        finally:
            browser.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_browser.py -v`
Expected: `1 passed` (takes a few seconds — it launches a real headless Chromium instance).

- [ ] **Step 5: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/browser.py tests/test_browser.py
git commit -m "feat: shared headless-browser fetch with cookie injection"
```

---

## Task 3: Cookie storage (`cookies.py`) — extract, load, secret handling

**Files:**
- Create: `src/mediumlm/cookies.py`
- Test: `tests/test_cookies.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cookies.py
import json
import os
import stat

import pytest

from mediumlm import cookies


class FakeCookie:
    def __init__(self, name, value, domain, path, secure):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure


def test_extract_writes_0600_permissions(tmp_path, monkeypatch):
    fake_jar = [FakeCookie("sid", "abc123", ".medium.com", "/", True)]
    monkeypatch.setattr("browser_cookie3.chrome", lambda domain_name: fake_jar)

    target = tmp_path / "cookies.json"
    result = cookies.extract_cookies(path=target)

    assert result == [
        {"name": "sid", "value": "abc123", "domain": ".medium.com", "path": "/", "secure": True}
    ]
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600


def test_extract_refuses_git_tracked_path(tmp_path, monkeypatch):
    monkeypatch.setattr("browser_cookie3.chrome", lambda domain_name: [])
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    target = repo / "cookies.json"

    with pytest.raises(cookies.GitTrackedPathError):
        cookies.extract_cookies(path=target)


def test_extract_rejects_unsupported_browser(tmp_path):
    with pytest.raises(ValueError):
        cookies.extract_cookies(browser="firefox", path=tmp_path / "cookies.json")


def test_load_cookies_missing_file_raises(tmp_path):
    with pytest.raises(cookies.CookiesNotFoundError):
        cookies.load_cookies(path=tmp_path / "nope.json")


def test_load_cookies_round_trip(tmp_path, monkeypatch):
    fake_jar = [FakeCookie("uid", "u1", ".medium.com", "/", True)]
    monkeypatch.setattr("browser_cookie3.chrome", lambda domain_name: fake_jar)
    target = tmp_path / "cookies.json"

    cookies.extract_cookies(path=target)
    loaded = cookies.load_cookies(path=target)

    assert loaded == [
        {"name": "uid", "value": "u1", "domain": ".medium.com", "path": "/", "secure": True}
    ]


def test_check_cookies_authenticated(tmp_path, monkeypatch):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    class FakePage:
        status = 200
        final_url = "https://medium.com/me/settings"
        title = "Settings – Medium"
        html = "<html></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = cookies.check_cookies(path=cookie_path)

    assert result == {"authenticated": True, "final_url": "https://medium.com/me/settings"}


def test_check_cookies_detects_signin_redirect(tmp_path, monkeypatch):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "expired", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    class FakePage:
        status = 200
        final_url = "https://medium.com/m/signin?operation=login"
        title = "Sign in – Medium"
        html = "<html></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = cookies.check_cookies(path=cookie_path)

    assert result["authenticated"] is False


def test_check_cookies_missing_file_raises(tmp_path):
    with pytest.raises(cookies.CookiesNotFoundError):
        cookies.check_cookies(path=tmp_path / "nope.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cookies.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.cookies'` (or `ImportError`) for every test.

- [ ] **Step 3: Implement `cookies.py`**

```python
# src/mediumlm/cookies.py
"""Cookie storage for the Medium session used by mediumlm.

The stored cookie file is a bearer-token-equivalent secret (it grants
the same access as the logged-in Medium session it was extracted
from), so it is written with 0600 permissions and this module refuses
to write it into any git-tracked directory.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import List, Optional

DEFAULT_COOKIE_DIR = Path.home() / ".mediumlm"
DEFAULT_COOKIE_PATH = DEFAULT_COOKIE_DIR / "cookies.json"

CHECK_URL = "https://medium.com/me/settings"


class CookiesNotFoundError(Exception):
    """Raised when no cookie file exists at the expected path."""


class GitTrackedPathError(Exception):
    """Raised when asked to write cookies into a git-tracked directory."""


def _is_under_git_repo(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    candidates = [resolved.parent, *resolved.parent.parents]
    return any((parent / ".git").exists() for parent in candidates)


def extract_cookies(browser: str = "chrome", path: Optional[Path] = None) -> List[dict]:
    """Extract medium.com cookies from the local browser cookie store."""
    if browser != "chrome":
        raise ValueError(f"unsupported browser: {browser}")

    target = Path(path) if path else DEFAULT_COOKIE_PATH
    if _is_under_git_repo(target):
        raise GitTrackedPathError(
            f"{target} is inside a git-tracked directory; pass --path to an "
            "untracked location instead."
        )

    import browser_cookie3

    jar = browser_cookie3.chrome(domain_name="medium.com")
    extracted = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
        }
        for c in jar
    ]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(extracted, indent=2))
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return extracted


def load_cookies(path: Optional[Path] = None) -> List[dict]:
    target = Path(path) if path else DEFAULT_COOKIE_PATH
    if not target.exists():
        raise CookiesNotFoundError(
            f"no cookie file at {target}; run `mediumlm cookies extract` first"
        )
    return json.loads(target.read_text())


def check_cookies(path: Optional[Path] = None) -> dict:
    """Confirm the stored cookies still authenticate against Medium.

    A stale/expired session gets redirected to Medium's sign-in page;
    checking the post-navigation URL is more reliable than scanning
    page text for "sign in" (which appears on logged-in pages too, in
    nav menus).
    """
    from . import browser as browser_mod

    loaded = load_cookies(path=path)
    page = browser_mod.fetch_page(CHECK_URL, loaded)
    authenticated = "/m/signin" not in page.final_url
    return {"authenticated": authenticated, "final_url": page.final_url}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cookies.py -v`
Expected: all 8 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/cookies.py tests/test_cookies.py
git commit -m "feat: cookie extraction, loading, and session check"
```

---

## Task 4: Pure HTML parsing — access detection & markdown extraction

**Files:**
- Create: `src/mediumlm/parsing.py`
- Create: `tests/fixtures/full_article.html`
- Create: `tests/fixtures/blocked_cloudflare.html`
- Create: `tests/fixtures/signed_out_preview.html`
- Create: `tests/fixtures/not_member_preview.html`
- Test: `tests/test_parsing.py`

These are pure functions — no network, no browser — so they run instantly and are the core regression protection for "never silently return a preview as if it were the full article" (the spec's most important error-handling requirement).

- [ ] **Step 1: Create the fixture files**

```bash
mkdir -p /Users/pisitkoolplukpol/Work/mediumlm/tests/fixtures
```

`tests/fixtures/full_article.html`:
```html
<html>
<head><title>My Great Article – Medium</title></head>
<body>
<nav><a href="/">Home</a></nav>
<article>
<h1>My Great Article</h1>
<p>This is the first paragraph of a full, unblocked article that a
real member account should be able to read in its entirety, with no
paywall meter and no sign-in prompt anywhere on the page.</p>
<p>This is a second paragraph, continuing the story well past the
point where a preview or metered paywall would normally cut a
non-member reader off, so that the total visible article text is
comfortably longer than the full-article length threshold used by
the access-detection heuristic in parsing.py.</p>
<p>A third paragraph adds still more real content, describing the
kind of long-form writing typical of a Medium post, to make sure the
extracted markdown is substantial and clearly not a truncated
preview snippet.</p>
</article>
</body>
</html>
```

`tests/fixtures/blocked_cloudflare.html`:
```html
<html>
<head><title>Just a moment...</title></head>
<body>
<div id="challenge-running">
Checking your browser before accessing medium.com.
This process is automatic. Your browser will redirect shortly.
Please enable Cookies and reload the page.
This is a Cloudflare challenge page.
</div>
</body>
</html>
```

`tests/fixtures/signed_out_preview.html`:
```html
<html>
<head><title>Some Article – Medium</title></head>
<body>
<nav>
<a href="/m/signin">Sign in</a>
<a href="/m/signup">Sign up</a>
</nav>
<article>
<h1>Some Article</h1>
<p>Short preview text only, not the full story body, because the
session used to load this page isn't actually signed in — the
cookies have expired or never authenticated in the first place.</p>
</article>
</body>
</html>
```

`tests/fixtures/not_member_preview.html`:
```html
<html>
<head><title>Member Story – Medium</title></head>
<body>
<article>
<h1>Member Story</h1>
<p class="meteredContent">Member-only story</p>
<p>This is only the preview paragraph shown to signed-in accounts
that are not Medium members, before the paywall cuts off the rest of
the content that only paying members can read.</p>
</article>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_parsing.py
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


def test_extract_article_markdown_pulls_article_body_only():
    html = _load("full_article.html")
    markdown = parsing.extract_article_markdown(html)
    assert "My Great Article" in markdown
    assert "Home" not in markdown  # nav link outside <article> must be excluded
    assert len(markdown) > 400
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_parsing.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.parsing'` for every test.

- [ ] **Step 4: Implement `parsing.py`**

```python
# src/mediumlm/parsing.py
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
        a.get("href", "").startswith(marker)
        for marker in SIGNED_OUT_HREF_MARKERS
        for a in soup.find_all("a")
    )
    article = soup.find("article")
    article_text = article.get_text(" ", strip=True) if article else ""
    is_member_gated = MEMBER_ONLY_MARKER in html.lower()

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_parsing.py -v`
Expected: all 5 tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/parsing.py tests/test_parsing.py tests/fixtures/*.html
git commit -m "feat: pure HTML access-detection and markdown extraction"
```

---

## Task 5: Article fetch orchestration (`fetch.py`)

**Files:**
- Create: `src/mediumlm/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_fetch.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.fetch'`.

- [ ] **Step 3: Implement `fetch.py`**

```python
# src/mediumlm/fetch.py
"""High-level article fetch: browser + parsing composed together."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import browser as browser_mod
from . import parsing


@dataclass
class ArticleResult:
    url: str
    title: str
    access: str
    access_reason: Optional[str]
    markdown: str


def fetch_article(url: str, cookies: List[dict]) -> ArticleResult:
    page = browser_mod.fetch_page(url, cookies)
    access, reason = parsing.detect_access(page.html, page.title)
    markdown = parsing.extract_article_markdown(page.html)
    return ArticleResult(
        url=url,
        title=page.title,
        access=access,
        access_reason=reason,
        markdown=markdown,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_fetch.py -v`
Expected: both tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/fetch.py tests/test_fetch.py
git commit -m "feat: fetch_article orchestration on top of browser + parsing"
```

---

## Task 6: Medium search (`search.py`)

**Files:**
- Create: `src/mediumlm/search.py`
- Create: `tests/fixtures/search_results.html`
- Test: `tests/test_search.py`

- [ ] **Step 1: Create the search-results fixture**

`tests/fixtures/search_results.html`:
```html
<html>
<head><title>mcp - Medium Search</title></head>
<body>
<nav><a href="/m/signin">Sign in</a></nav>
<div class="stream">
<a href="https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b">I Connected These 7 MCPs to Claude</a>
<a href="/@janedoe/another-great-post-1a2b3c4d5e6f">Another Great Post</a>
<a href="/@janedoe">Jane Doe profile</a>
<a href="/search?q=mcp">search again</a>
</div>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_search.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_search.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.search'`.

- [ ] **Step 4: Implement `search.py`**

```python
# src/mediumlm/search.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_search.py -v`
Expected: both tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/search.py tests/test_search.py tests/fixtures/search_results.html
git commit -m "feat: Medium search via headless-browser-driven search page"
```

---

## Task 7: CLI (`cli.py`)

**Files:**
- Create: `src/mediumlm/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import json

from mediumlm import cli
from mediumlm.search import SearchResult


def test_cookies_extract_reports_git_tracked_path_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("browser_cookie3.chrome", lambda domain_name: [])
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    target = repo / "cookies.json"

    exit_code = cli.main(["cookies", "extract", "--path", str(target)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "git-tracked" in captured.err


def test_cookies_check_missing_file_reports_clear_error(tmp_path, capsys):
    missing = tmp_path / "no-cookies.json"

    exit_code = cli.main(["cookies", "check", "--path", str(missing)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "cookies extract" in captured.err


def test_fetch_missing_cookies_reports_clear_error(tmp_path, capsys):
    missing = tmp_path / "no-cookies.json"

    exit_code = cli.main(
        ["fetch", "https://medium.com/@a/b-abc123abc123", "--path", str(missing)]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "cookies extract" in captured.err


def test_search_prints_json_results(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    monkeypatch.setattr(
        "mediumlm.search.search",
        lambda query, cookies, limit: [
            SearchResult(title="Some Article", url="https://medium.com/@a/some-article-abc123abc123")
        ],
    )

    exit_code = cli.main(["search", "test topic", "--path", str(cookie_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload[0]["title"] == "Some Article"


def test_fetch_prints_json_result(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_article",
        lambda url, cookies: ArticleResult(
            url=url, title="Some Article", access="full", access_reason=None, markdown="# Some Article"
        ),
    )

    exit_code = cli.main(
        ["fetch", "https://medium.com/@a/some-article-abc123abc123", "--path", str(cookie_path)]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["access"] == "full"
    assert payload["markdown"] == "# Some Article"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.cli'`.

- [ ] **Step 3: Implement `cli.py`**

```python
# src/mediumlm/cli.py
"""Command-line entry point for mediumlm."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import cookies as cookies_mod
from . import fetch as fetch_mod
from . import search as search_mod


def _cmd_cookies_extract(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        result = cookies_mod.extract_cookies(browser=args.browser, path=path)
    except cookies_mod.GitTrackedPathError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"cookie_count": len(result)}))
    return 0


def _cmd_cookies_check(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        result = cookies_mod.check_cookies(path=path)
    except cookies_mod.CookiesNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0 if result["authenticated"] else 1


def _cmd_search(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        loaded = cookies_mod.load_cookies(path=path)
    except cookies_mod.CookiesNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    results = search_mod.search(args.query, cookies=loaded, limit=args.limit)
    print(json.dumps([dataclasses.asdict(r) for r in results]))
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        loaded = cookies_mod.load_cookies(path=path)
    except cookies_mod.CookiesNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = fetch_mod.fetch_article(args.url, cookies=loaded)
    print(json.dumps(dataclasses.asdict(result)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mediumlm")
    sub = parser.add_subparsers(dest="command", required=True)

    cookies_parser = sub.add_parser("cookies")
    cookies_sub = cookies_parser.add_subparsers(dest="cookies_command", required=True)

    extract_parser = cookies_sub.add_parser("extract")
    extract_parser.add_argument("--browser", default="chrome")
    extract_parser.add_argument("--path")
    extract_parser.set_defaults(func=_cmd_cookies_extract)

    check_parser = cookies_sub.add_parser("check")
    check_parser.add_argument("--path")
    check_parser.set_defaults(func=_cmd_cookies_check)

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=8)
    search_parser.add_argument("--path")
    search_parser.set_defaults(func=_cmd_search)

    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--path")
    fetch_parser.set_defaults(func=_cmd_fetch)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cli.py -v`
Expected: all 5 tests `PASSED`.

- [ ] **Step 5: Run the full test suite**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/ -v`
Expected: all tests across every module `PASSED` (browser, cookies, parsing, fetch, search, cli).

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/cli.py tests/test_cli.py
git commit -m "feat: mediumlm CLI wiring cookies/search/fetch commands"
```

---

## Task 8: Verify the installed `mediumlm` command works end-to-end (mechanics, not live Medium)

**Files:** none (verification only)

- [ ] **Step 1: Confirm the console script is installed and wired**

Run: `mediumlm --help`
Expected: usage text listing the `cookies`, `search`, and `fetch` subcommands (no import errors — confirms the editable install's console-script entry point resolves `mediumlm.cli:main` correctly now that the module exists).

- [ ] **Step 2: Confirm `cookies extract` works against your real Chrome session**

Run: `mediumlm cookies extract`
Expected: `{"cookie_count": N}` with `N > 0`, and `~/.mediumlm/cookies.json` created with `0600` permissions:

```bash
ls -la ~/.mediumlm/cookies.json
stat -f "%Lp" ~/.mediumlm/cookies.json
```
Expected permissions output: `600`.

- [ ] **Step 3: Confirm `cookies check` reports authenticated**

Run: `mediumlm cookies check`
Expected: `{"authenticated": true, "final_url": "https://medium.com/me/settings"}`, exit code `0`.

(No commit for this task — it's a verification checkpoint, not a code change.)

---

## Task 9: Skill wrapper (`~/.claude/skills/mediumlm/SKILL.md`)

**Files:**
- Create: `~/.claude/skills/mediumlm/SKILL.md`

- [ ] **Step 1: Create the skill directory and file**

```bash
mkdir -p ~/.claude/skills/mediumlm
```

Write `~/.claude/skills/mediumlm/SKILL.md`:

```markdown
---
name: mediumlm
description: Research a topic on Medium using the user's own logged-in Medium session (cookies extracted from Chrome). Searches Medium, fetches full article text including member-only content, and produces a chat summary, a saved research note, and optionally NotebookLM artifacts. Activates on explicit /mediumlm <topic> or intent like "research X on Medium" / "what does Medium say about X".
---

# mediumlm

Drives the `mediumlm` CLI (installed from
`/Users/pisitkoolplukpol/Work/mediumlm`, editable install via
`pip3 install -e ".[dev]"`) to research a Medium topic using the
user's own session — see that project's
`docs/superpowers/specs/2026-07-14-mediumlm-design.md` for the full
design and rationale.

## Prerequisites

1. `mediumlm --help` must run without error (confirms the package is
   installed). If not: `cd /Users/pisitkoolplukpol/Work/mediumlm && pip3 install -e ".[dev]"`.
2. `python3 -m playwright install chromium` must have been run once on
   this machine.
3. Chrome must be open and logged into Medium the first time cookies
   are extracted (or whenever they go stale).

## Workflow for `/mediumlm <topic>`

1. **Check the session.** Run `mediumlm cookies check`.
   - If it reports `"authenticated": false` or exits non-zero: stop
     and tell the user to open Chrome, confirm they're logged into
     medium.com, then run `mediumlm cookies extract`. Do not proceed
     with a stale session — never silently continue as if it worked.

2. **Search.** Run `mediumlm search "<topic>" --limit 8`. This returns
   a JSON array of `{title, url}`. If it returns an empty array,
   report that plainly to the user — do not fabricate results.

3. **Fetch.** For each relevant result (or all of them, for a narrow
   topic), run `mediumlm fetch <url>`. Each call returns JSON:
   `{url, title, access, access_reason, markdown}`.
   - `access: "full"` — use the markdown as the article's real content.
   - `access: "preview"` — the article was NOT fully read. Label it
     clearly in every output as "preview only" and state the
     `access_reason` (`blocked`, `cookies_expired`, or `not_member`).
     Never blend preview-only content into a summary as if it were
     the full article.

4. **Produce all three outputs:**
   - **Chat answer** — synthesize a summary/answer to the user's
     question directly from the fetched (full-access) article text.
   - **Saved research note** — write to
     `docs/research/medium/<topic-slug>-<YYYY-MM-DD>.md` inside the
     current project if it has a `docs/` convention, otherwise default
     to `~/Work/docs/research/medium/`. Include: the list of sources
     with URLs and their `access` status, key excerpts, and the
     synthesized summary.
   - **NotebookLM artifacts — only if the user explicitly asks** for a
     podcast/audio overview, mind map, or study guide. In that case,
     invoke the existing `notebooklm` skill: create a notebook, add
     each fetched article (by URL, or by pasting the fetched markdown
     as a text source if the URL alone won't render for NotebookLM),
     then generate the requested artifact type.

## Error handling — do not paper over these

- `cookies check` fails → stop, tell the user to re-extract. Do not
  proceed.
- `search` returns zero results → say so; do not invent articles.
- Any `fetch` result with `access != "full"` → label it explicitly in
  every output that uses it, with its `access_reason`.
- Repeated fetch/search failures in one run → stop and report the
  failure; do not retry in a loop (Medium's bot detection is exactly
  what a retry loop would trip further).

## Scope

This is for the user's own personal research against their own Medium
account, at normal single-topic, on-demand volume — not bulk scraping.
See the design spec's Error Handling section for the account-risk
rationale.
```

- [ ] **Step 2: Verify the skill file is valid**

Run: `cat ~/.claude/skills/mediumlm/SKILL.md | head -5`
Expected: shows the YAML frontmatter with `name: mediumlm` and a `description` field — confirms the file was written correctly.

(No git commit — `~/.claude/skills/` is outside the `mediumlm` project repo and is not itself under version control here.)

---

## Task 10: Manual end-to-end verification against real Medium

**Files:** none (verification only — this is the checklist from the design spec's Testing section, run for real)

- [ ] **Step 1: Fresh cookie extraction**

Run: `mediumlm cookies extract`
Expected: succeeds; `~/.mediumlm/cookies.json` has fresh content.

- [ ] **Step 2: Search a real topic**

Run: `mediumlm search "claude code mcp" --limit 5`
Expected: JSON array of real Medium articles with plausible titles/URLs (not empty, not fabricated — actual current search results).

- [ ] **Step 3: Fetch a known free article**

Run: `mediumlm fetch "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b"`
Expected: `"access": "full"`, and the `markdown` field contains real article text (e.g. mentions "MCP", "Playwright MCP" — matches the content already observed during the design spike).

- [ ] **Step 4: Fetch a member-only article you have access to**

Pick a real member-only Medium article your account can read. Run:
`mediumlm fetch "<that URL>"`
Expected: `"access": "full"`, complete article text — not a truncated preview.

- [ ] **Step 5: Simulate stale cookies**

```bash
mv ~/.mediumlm/cookies.json ~/.mediumlm/cookies.json.bak
mediumlm cookies check
```
Expected: exits non-zero with a clear `error: no cookie file at ...` message on stderr — not a silent empty/success result. Restore afterward:
```bash
mv ~/.mediumlm/cookies.json.bak ~/.mediumlm/cookies.json
```

- [ ] **Step 6: Run a full `/mediumlm <topic>` request through Claude**

In a Claude Code session with the skill installed, ask: `/mediumlm claude code mcp servers`. Confirm all three outputs appear: a chat summary, a saved note under `docs/research/medium/`, and correct labeling of any `preview`-access sources.

- [ ] **Step 7: Final commit marking the implementation complete**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add -A
git status  # confirm only expected files are staged — no stray cookies.json, no venv
git commit -m "chore: complete mediumlm v1 implementation and manual verification"
```
