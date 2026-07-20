# Batch Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mediumlm fetch` accepts multiple URLs and fetches them through one shared headless-browser session, cutting the ~4–6s Chromium launch overhead from per-article to per-batch.

**Architecture:** A `BrowserSession` context manager in `browser.py` owns the Playwright lifecycle (launch → context with cookies → one page reused across navigations); the existing `fetch_page` becomes a one-shot wrapper around it so `search.py`, `cookies.py`, and every existing test keep working unchanged. `fetch.py` gains `fetch_articles(urls, cookies)` which drives one session across all URLs and converts per-URL failures into explicit `access: "error"` results (new optional `error` field on `ArticleResult`) instead of aborting the batch — partial failure stays observable, never silent. The CLI's `fetch` subcommand takes `nargs="+"`: one URL preserves today's exact contract (single JSON object; `error:` on stderr + exit 1 on failure), multiple URLs print a JSON array and exit 1 only when every fetch failed.

**Tech Stack:** Python 3.9+, Playwright (headless Chromium), pytest. No new dependencies.

**Reference:** `docs/superpowers/specs/2026-07-14-mediumlm-design.md` for the overall design; this plan extends the fetch path only. Current code state as of commit `7e66c33` (README update) — note `parsing.detect_access(html, title, status=...)` takes a keyword `status` argument and `cli.main` has a catch-all `except Exception` returning 1.

---

## Task 1: `BrowserSession` — shared headless session (`browser.py`)

**Files:**
- Modify: `src/mediumlm/browser.py`
- Test: `tests/test_browser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_browser.py` (it already defines `_EchoCookieHandler` and imports `threading`, `HTTPServer`, and `browser` — reuse those):

```python
def test_browser_session_fetches_multiple_pages_in_one_session():
    server = HTTPServer(("127.0.0.1", 0), _EchoCookieHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with browser.BrowserSession(
            cookies=[
                {
                    "name": "probe",
                    "value": "hello123",
                    "domain": "127.0.0.1",
                    "path": "/",
                    "secure": False,
                }
            ],
            settle_ms=100,
        ) as session:
            first = session.fetch(f"http://127.0.0.1:{port}/first")
            second = session.fetch(f"http://127.0.0.1:{port}/second")
        assert first.status == 200
        assert second.status == 200
        assert "hello123" in first.html
        assert "hello123" in second.html
        assert first.title == "echo"
        assert second.title == "echo"
    finally:
        server.shutdown()
        thread.join()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_browser.py -v`
Expected: the new test FAILS with `AttributeError: module 'mediumlm.browser' has no attribute 'BrowserSession'`; the existing `test_fetch_page_injects_cookies_into_the_request` still PASSES.

- [ ] **Step 3: Implement `BrowserSession` and refactor `fetch_page` onto it**

In `src/mediumlm/browser.py`, change the `typing` import to include `Optional`:

```python
from typing import List, Optional
```

Then replace the entire existing `fetch_page` function with:

```python
class BrowserSession:
    """One headless browser reused across multiple fetches.

    Launching Chromium dominates per-article latency (~4-6s per
    launch); a batch of N articles through one session pays that cost
    once. A single page is reused across navigations — per-URL `goto`
    failures (timeout, DNS) leave the page navigable for the next URL.
    """

    def __init__(self, cookies: List[dict], settle_ms: int = 2000):
        self._cookies = cookies
        self._settle_ms = settle_ms
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            context = self._browser.new_context(user_agent=USER_AGENT)
            context.add_cookies(_to_playwright_cookies(self._cookies))
            self._page = context.new_page()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def fetch(self, url: str, settle_ms: Optional[int] = None) -> PageResult:
        """Load `url` in this session's page and return the settled result.

        Uses wait_until="load", not "networkidle" — Medium's page never
        goes fully network-idle (ongoing analytics/background requests),
        which caused "networkidle" to time out in the design spike.
        """
        wait = self._settle_ms if settle_ms is None else settle_ms
        response = self._page.goto(url, wait_until="load", timeout=45000)
        self._page.wait_for_timeout(wait)
        return PageResult(
            status=response.status if response else 0,
            final_url=self._page.url,
            title=self._page.title(),
            html=self._page.content(),
        )


def fetch_page(url: str, cookies: List[dict], settle_ms: int = 2000) -> PageResult:
    """One-shot fetch: a `BrowserSession` for a single URL."""
    with BrowserSession(cookies, settle_ms=settle_ms) as session:
        return session.fetch(url)
```

- [ ] **Step 4: Run the browser tests to verify both pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_browser.py -v`
Expected: 2 passed (each launches a real headless Chromium, a few seconds each).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/ -q`
Expected: 40 passed (39 existing + 1 new). `search.py` and `cookies.py` call `fetch_page`, which still exists with the same signature.

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/browser.py tests/test_browser.py
git commit -m "feat: BrowserSession reuses one headless browser across fetches"
```

---

## Task 2: `fetch_articles` batch orchestration (`fetch.py`)

**Files:**
- Modify: `src/mediumlm/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch.py`:

```python
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_fetch.py -v`
Expected: the 2 new tests FAIL with `AttributeError: module 'mediumlm.fetch' has no attribute 'fetch_articles'`; the 2 existing tests still PASS.

- [ ] **Step 3: Implement `error` field and `fetch_articles`**

In `src/mediumlm/fetch.py`, add an `error` field (defaulted, so existing constructions stay valid) to `ArticleResult`:

```python
@dataclass
class ArticleResult:
    url: str
    title: str
    access: str
    access_reason: Optional[str]
    markdown: str
    error: Optional[str] = None
```

Then append after `fetch_article`:

```python
def fetch_articles(urls: List[str], cookies: List[dict]) -> List[ArticleResult]:
    """Fetch several articles through one shared browser session.

    A failure on one URL is recorded as an `access: "error"` result
    (with the exception text in `error`) and the batch continues —
    partial failure is returned explicitly, never raised away or
    silently dropped. Results preserve input order.
    """
    results: List[ArticleResult] = []
    with browser_mod.BrowserSession(cookies) as session:
        for url in urls:
            try:
                page = session.fetch(url)
            except Exception as exc:
                results.append(
                    ArticleResult(
                        url=url,
                        title="",
                        access="error",
                        access_reason=None,
                        markdown="",
                        error=str(exc),
                    )
                )
                continue
            access, reason = parsing.detect_access(
                page.html, page.title, status=page.status
            )
            results.append(
                ArticleResult(
                    url=url,
                    title=page.title,
                    access=access,
                    access_reason=reason,
                    markdown=parsing.extract_article_markdown(page.html),
                )
            )
    return results
```

`fetch_article` stays exactly as it is — single-article callers and its existing tests are untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_fetch.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/fetch.py tests/test_fetch.py
git commit -m "feat: fetch_articles batch orchestration with explicit per-URL error results"
```

---

## Task 3: CLI multi-URL support (`cli.py`)

**Files:**
- Modify: `src/mediumlm/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Update the existing single-URL test and add batch tests**

In `tests/test_cli.py`, the existing `test_fetch_prints_json_result` monkeypatches `mediumlm.fetch.fetch_article`; the CLI now routes everything through `fetch_articles`, so REPLACE that test's monkeypatch block. The full replacement test:

```python
def test_fetch_prints_json_result(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies: [
            ArticleResult(
                url=urls[0], title="Some Article", access="full",
                access_reason=None, markdown="# Some Article",
            )
        ],
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

Then append three new tests:

```python
def test_fetch_multiple_urls_prints_json_array(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies: [
            ArticleResult(url=u, title=f"T{i}", access="full", access_reason=None, markdown=f"# T{i}")
            for i, u in enumerate(urls)
        ],
    )

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert [p["title"] for p in payload] == ["T0", "T1"]


def test_fetch_single_url_error_result_reports_stderr_and_exit_1(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies: [
            ArticleResult(url=urls[0], title="", access="error",
                          access_reason=None, markdown="", error="net::ERR_TIMED_OUT")
        ],
    )

    exit_code = cli.main(
        ["fetch", "https://medium.com/@a/bad-abc123abc123", "--path", str(cookie_path)]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERR_TIMED_OUT" in captured.err


def test_fetch_batch_all_failed_exits_1_but_still_prints_array(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies: [
            ArticleResult(url=u, title="", access="error",
                          access_reason=None, markdown="", error="boom")
            for u in urls
        ],
    )

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
    ])

    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert len(payload) == 2
    assert all(p["access"] == "error" for p in payload)
    assert "all 2 fetches failed" in captured.err
```

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cli.py -v`
Expected: `test_fetch_prints_json_result` and the 3 new tests FAIL (the CLI still calls `fetch_article` and its parser rejects/ignores extra URLs); the other CLI tests PASS.

- [ ] **Step 3: Implement the CLI changes**

In `src/mediumlm/cli.py`, replace the whole `_cmd_fetch` function with:

```python
def _cmd_fetch(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        loaded = cookies_mod.load_cookies(path=path)
    except cookies_mod.CookiesNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    results = fetch_mod.fetch_articles(args.urls, cookies=loaded)
    failed = [r for r in results if r.access == "error"]
    if len(results) == 1:
        result = results[0]
        if result.access == "error":
            print(f"error: fetch failed for {result.url}: {result.error}", file=sys.stderr)
            return 1
        print(json.dumps(dataclasses.asdict(result)))
        return 0
    print(json.dumps([dataclasses.asdict(r) for r in results]))
    if failed and len(failed) == len(results):
        print(f"error: all {len(results)} fetches failed", file=sys.stderr)
        return 1
    return 0
```

And in `build_parser`, change the fetch subparser's positional from `url` to one-or-more `urls`:

```python
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("urls", nargs="+")
    fetch_parser.add_argument("--path")
    fetch_parser.set_defaults(func=_cmd_fetch)
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_cli.py -v`
Expected: all CLI tests PASS (9 total: 6 pre-existing including the updated one, plus 3 new).

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/ -q`
Expected: 45 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git add src/mediumlm/cli.py tests/test_cli.py
git commit -m "feat: mediumlm fetch accepts multiple URLs via one browser session"
```

---

## Task 4: Live verification, docs, and reinstall

**Files:**
- Modify: `README.md`
- Modify: `~/.claude/skills/mediumlm/SKILL.md` (outside the repo — edited but not committed here)

- [ ] **Step 1: Reinstall the uv tool from the updated source**

Run: `uv tool install --reinstall /Users/pisitkoolplukpol/Work/mediumlm`
Expected: ends with `Installed 1 executable: mediumlm`.

- [ ] **Step 2: Live batch fetch against real Medium — two known articles, one call**

Run:
```bash
time mediumlm fetch \
  "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b" \
  "https://medium.com/@the.gigi/claude-code-deep-dive-subagents-in-action-703cd8745769" \
  | python3 -c "import json,sys; [print(r['access'], len(r['markdown']), r['title'][:50]) for r in json.load(sys.stdin)]"
```
Expected: a JSON array of 2 results, both `full` with non-trivial markdown lengths (thousands of chars). Note the wall time; compare against two sequential single fetches:
```bash
time (mediumlm fetch "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b" > /dev/null; \
      mediumlm fetch "https://medium.com/@the.gigi/claude-code-deep-dive-subagents-in-action-703cd8745769" > /dev/null)
```
Expected: the batch call is meaningfully faster (one Chromium launch instead of two). Record both timings for the commit message.

- [ ] **Step 3: Verify single-URL behavior is unchanged**

Run: `mediumlm fetch "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b" | python3 -c "import json,sys; d=json.load(sys.stdin); print(type(d).__name__, d['access'])"`
Expected: `dict full` — a single object, not a one-element array.

- [ ] **Step 4: Update README.md**

In the Usage section, extend the fetch example to show batch usage. Replace the single `mediumlm fetch` example block with:

```bash
# Fetch a specific article's full text using your session
mediumlm fetch "https://medium.com/@author/article-slug-abc123abc123"

# Fetch several articles in one shared browser session (one Chromium
# launch for the whole batch instead of one per article); prints a
# JSON array in input order, with per-URL failures recorded as
# {"access": "error", "error": "<message>"} entries instead of
# aborting the batch
mediumlm fetch "https://medium.com/@a/first-abc123abc123" \
               "https://medium.com/@a/second-def456def456"
```

Also update the paragraph beneath it that describes output: after the sentence about `access`/`access_reason`, add that batch mode prints a JSON array, single-URL mode a single object, and the exit code is `1` only when every URL in a batch failed (single-URL failures keep the `error:`-on-stderr, empty-stdout contract).

- [ ] **Step 5: Update the skill (`~/.claude/skills/mediumlm/SKILL.md`)**

In the Workflow section step 3 (**Fetch**), replace the instruction to run `mediumlm fetch <url>` per result with: batch all chosen URLs into ONE call — `mediumlm fetch <url1> <url2> ...` — which returns a JSON array in input order; entries with `access: "error"` failed to fetch (message in `error`) and must be reported per-URL, not retried in a loop. Single-URL calls still return a single JSON object. In the Error handling section, add: an `access: "error"` entry in batch output is a per-URL hard failure — report it alongside the successful results; only a fully-failed batch exits non-zero.

- [ ] **Step 6: Full suite one last time, then commit the README (skill file is outside the repo)**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
python3 -m pytest tests/ -q
git add README.md
git commit -m "docs: document batch fetch usage and timings"
```
Expected before commit: 45 passed.
