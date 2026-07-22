# Article Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache full-access article fetches on disk so repeat fetches skip the network entirely, and wire the `/mediumlm` skill to accumulate research into an Obsidian vault corpus (article notes + topic hubs).

**Architecture:** URL normalization moves from `search.py` into a shared `urls.py`. A new `cache.py` stores one JSON file per article (SHA-256 of the normalized URL) plus an `index.json`, atomic writes, `0700` directory, only `access: "full"` ever cached. `fetch.fetch_articles` consults the cache before launching a browser (a session is created only when ≥1 URL misses) and writes full results back. The CLI gains `--no-cache` on fetch and `cache list` / `cache clear [--url]` subcommands. Vault-corpus logic lives entirely in SKILL.md (outside this repo) — no vault knowledge in Python.

**Tech Stack:** Python 3.9+ stdlib only for the cache (hashlib, json, tempfile, os). pytest. No new dependencies.

**Reference:** `docs/superpowers/specs/2026-07-22-article-cache-vault-corpus-design.md`. Baseline: v0.2.0, 52 tests passing. Work on branch `article-cache`.

**Test-isolation rule (applies to every task):** cache functions resolve the directory at call time via `_cache_dir()`, so tests isolate by monkeypatching `mediumlm.cache.DEFAULT_CACHE_DIR` to a tmp_path. Task 3 adds an autouse fixture to `tests/test_fetch.py` and `tests/test_cli.py` — without it, existing tests would write to the REAL `~/.mediumlm/cache/`.

---

## Task 1: Extract shared URL normalization (`urls.py`)

**Files:**
- Create: `src/mediumlm/urls.py`
- Modify: `src/mediumlm/search.py`
- Test: `tests/test_urls.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_urls.py
from mediumlm.urls import normalize_article_url


def test_relative_href_resolves_to_absolute_medium_url():
    assert (
        normalize_article_url("/@janedoe/post-1a2b3c4d5e6f")
        == "https://medium.com/@janedoe/post-1a2b3c4d5e6f"
    )


def test_query_and_fragment_are_stripped():
    assert (
        normalize_article_url("https://medium.com/@a/x-abc123abc123?source=home#frag")
        == "https://medium.com/@a/x-abc123abc123"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/pisitkoolplukpol/Work/mediumlm && python3 -m pytest tests/test_urls.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.urls'`.

- [ ] **Step 3: Create `src/mediumlm/urls.py`**

Move the body of `search._normalize_article_url` here unchanged, renamed public:

```python
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
```

- [ ] **Step 4: Update `search.py`**

Delete `_normalize_article_url` from `src/mediumlm/search.py`, add `from .urls import normalize_article_url` to its imports, and change the one call site in `parse_search_results` from `_normalize_article_url(href)` to `normalize_article_url(href)`. Remove the now-unused `urljoin, urlsplit, urlunsplit` names from search.py's `urllib.parse` import (keep `quote_plus`).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: 54 passed (52 + 2 new; search tests prove the move didn't change behavior).

- [ ] **Step 6: Commit**

```bash
git add src/mediumlm/urls.py src/mediumlm/search.py tests/test_urls.py
git commit -m "refactor: extract shared normalize_article_url into urls.py"
```

---

## Task 2: Cache module (`cache.py`)

**Files:**
- Create: `src/mediumlm/cache.py`
- Test: `tests/test_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cache.py
import json
import os
import stat

import pytest

from mediumlm import cache


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("mediumlm.cache.DEFAULT_CACHE_DIR", tmp_path / "cache")


def _full_result(url="https://medium.com/@a/x-abc123abc123", title="X"):
    return {
        "url": url,
        "title": title,
        "access": "full",
        "access_reason": None,
        "markdown": "# X",
        "error": None,
        "cached": False,
        "fetched_at": None,
    }


def test_round_trip_store_then_load():
    assert cache.store(_full_result()) is True
    entry = cache.load_cached("https://medium.com/@a/x-abc123abc123?source=home")
    assert entry is not None
    assert entry["markdown"] == "# X"
    assert entry["fetched_at"]  # stamped at store time


def test_cache_dir_created_private():
    cache.store(_full_result())
    mode = stat.S_IMODE(os.stat(cache.DEFAULT_CACHE_DIR).st_mode)
    assert mode == 0o700


def test_non_full_results_are_never_stored():
    preview = dict(_full_result(), access="preview", access_reason="not_member")
    error = dict(_full_result(), access="error", error="boom")
    assert cache.store(preview) is False
    assert cache.store(error) is False
    assert cache.load_cached(preview["url"]) is None


def test_corrupt_entry_is_a_miss_with_note(capsys):
    cache.store(_full_result())
    entry_path = next(p for p in cache.DEFAULT_CACHE_DIR.glob("*.json") if p.name != "index.json")
    entry_path.write_text("{not json")
    assert cache.load_cached("https://medium.com/@a/x-abc123abc123") is None
    assert "corrupt" in capsys.readouterr().err


def test_corrupt_index_lists_empty_with_note(capsys):
    cache.store(_full_result())
    (cache.DEFAULT_CACHE_DIR / "index.json").write_text("{not json")
    assert cache.list_entries() == []
    assert "corrupt" in capsys.readouterr().err


def test_list_entries_shape_and_empty():
    assert cache.list_entries() == []
    cache.store(_full_result())
    entries = cache.list_entries()
    assert len(entries) == 1
    assert entries[0]["url"] == "https://medium.com/@a/x-abc123abc123"
    assert entries[0]["title"] == "X"
    assert entries[0]["fetched_at"]


def test_clear_all_and_clear_single_url():
    cache.store(_full_result())
    cache.store(_full_result(url="https://medium.com/@b/y-def456def456", title="Y"))
    assert cache.clear(url="https://medium.com/@a/x-abc123abc123") == 1
    assert cache.load_cached("https://medium.com/@a/x-abc123abc123") is None
    assert cache.load_cached("https://medium.com/@b/y-def456def456") is not None
    assert cache.clear() == 1
    assert cache.list_entries() == []


def test_clear_refuses_paths_outside_cache_dir(monkeypatch):
    cache.store(_full_result())
    monkeypatch.setattr("mediumlm.cache.cache_key", lambda url: "../../evil")
    with pytest.raises(ValueError):
        cache.clear(url="https://medium.com/@a/x-abc123abc123")


def test_unreadable_cache_dir_store_fails_soft(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setattr("mediumlm.cache.DEFAULT_CACHE_DIR", blocker / "cache")
    assert cache.store(_full_result()) is False
    assert "cache write failed" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cache.py -v`
Expected: `ModuleNotFoundError: No module named 'mediumlm.cache'` for every test.

- [ ] **Step 3: Implement `src/mediumlm/cache.py`**

```python
"""Article cache: raw full-access fetch results stored per URL.

Only `access == "full"` results are ever cached — previews, blocked
pages, and errors must retry on the next run. Cached member-only
article text is private content, so the cache directory is created
0700. Cache failures never block research: every failure path
degrades to a cache miss with a `note:` line on stderr.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .urls import normalize_article_url

DEFAULT_CACHE_DIR = Path.home() / ".mediumlm" / "cache"
INDEX_NAME = "index.json"


def _cache_dir(cache_dir: Optional[Path]) -> Path:
    return Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR


def cache_key(url: str) -> str:
    return hashlib.sha256(normalize_article_url(url).encode("utf-8")).hexdigest()


def _note(message: str) -> None:
    print(f"note: {message}", file=sys.stderr)


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _atomic_write(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_cached(url: str, cache_dir: Optional[Path] = None) -> Optional[dict]:
    """Return the cached entry dict for `url`, or None on miss.

    A corrupt entry is a miss (with a stderr note) — the next
    successful store simply overwrites it.
    """
    directory = _cache_dir(cache_dir)
    entry_path = directory / f"{cache_key(url)}.json"
    if not entry_path.exists():
        return None
    entry = _read_json(entry_path)
    if entry is None:
        _note(f"cache entry for {normalize_article_url(url)} is corrupt; refetching")
        return None
    return entry


def store(result: dict, cache_dir: Optional[Path] = None) -> bool:
    """Cache a fetch-result dict. Returns True only when stored.

    Non-"full" results are rejected (False). Write failures degrade
    to a stderr note and False — the fetch itself already succeeded,
    so a broken cache must never fail the run.
    """
    if result.get("access") != "full":
        return False
    directory = _cache_dir(cache_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        normalized = normalize_article_url(result["url"])
        entry = dict(result)
        entry["url"] = normalized
        entry.pop("cached", None)
        if not entry.get("fetched_at"):
            entry["fetched_at"] = datetime.now(timezone.utc).isoformat()
        entry_name = f"{cache_key(normalized)}.json"
        _atomic_write(directory / entry_name, entry)
        index = _read_json(directory / INDEX_NAME) or {}
        index[normalized] = {
            "title": entry.get("title", ""),
            "fetched_at": entry["fetched_at"],
            "file": entry_name,
        }
        _atomic_write(directory / INDEX_NAME, index)
        return True
    except OSError as exc:
        _note(f"cache write failed ({exc}); continuing without cache")
        return False


def list_entries(cache_dir: Optional[Path] = None) -> List[dict]:
    directory = _cache_dir(cache_dir)
    index_path = directory / INDEX_NAME
    if not index_path.exists():
        return []
    index = _read_json(index_path)
    if index is None:
        _note("cache index is corrupt; listing empty")
        return []
    return [
        {
            "url": url,
            "title": meta.get("title", ""),
            "fetched_at": meta.get("fetched_at", ""),
        }
        for url, meta in sorted(index.items())
    ]


def clear(url: Optional[str] = None, cache_dir: Optional[Path] = None) -> int:
    """Delete the whole cache, or a single URL's entry.

    Refuses to delete anything whose resolved path falls outside the
    cache directory. Returns the number of article entries removed
    (the index file itself is not counted).
    """
    directory = _cache_dir(cache_dir).resolve()
    if not directory.exists():
        return 0

    def _ensure_contained(path: Path) -> None:
        resolved = path.resolve()
        if resolved != directory and directory not in resolved.parents:
            raise ValueError(f"refusing to delete outside cache dir: {resolved}")

    if url is None:
        removed = 0
        for entry_path in directory.glob("*.json"):
            _ensure_contained(entry_path)
            if entry_path.name != INDEX_NAME:
                removed += 1
            entry_path.unlink()
        return removed

    normalized = normalize_article_url(url)
    entry_path = directory / f"{cache_key(normalized)}.json"
    _ensure_contained(entry_path)
    removed = 0
    if entry_path.exists():
        entry_path.unlink()
        removed = 1
    index_path = directory / INDEX_NAME
    index = _read_json(index_path)
    if index is not None and normalized in index:
        del index[normalized]
        _atomic_write(index_path, index)
    return removed
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_cache.py -v`
Expected: all 10 tests PASS. Then `python3 -m pytest tests/ -q` → 64 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mediumlm/cache.py tests/test_cache.py
git commit -m "feat: article cache with atomic writes, index, and containment-checked clear"
```

---

## Task 3: Fetch integration

**Files:**
- Modify: `src/mediumlm/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Add the autouse cache-isolation fixture and failing tests**

At the top of `tests/test_fetch.py` (after imports; add `import pytest` if missing):

```python
@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("mediumlm.cache.DEFAULT_CACHE_DIR", tmp_path / "cache")
```

Append these tests (reuse the existing `_FakePage`, `_FakeSession`, `_full_article_html` helpers):

```python
def test_fetch_articles_all_cache_hits_never_launch_browser(monkeypatch):
    from mediumlm import cache as cache_mod

    url = "https://medium.com/@a/first-abc123abc123"
    cache_mod.store({
        "url": url, "title": "First – Medium", "access": "full",
        "access_reason": None, "markdown": "# First", "error": None,
        "cached": False, "fetched_at": None,
    })

    constructed = []
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession",
        lambda cookies, settle_ms=2000: constructed.append(1) or None,
    )

    results = fetch.fetch_articles([url], cookies=[])

    assert constructed == []  # no browser at all
    assert results[0].cached is True
    assert results[0].access == "full"
    assert results[0].markdown == "# First"
    assert results[0].fetched_at


def test_fetch_articles_mixes_cached_and_live_preserving_order(monkeypatch):
    from mediumlm import cache as cache_mod

    cached_url = "https://medium.com/@a/first-abc123abc123"
    live_url = "https://medium.com/@a/second-def456def456"
    cache_mod.store({
        "url": cached_url, "title": "First – Medium", "access": "full",
        "access_reason": None, "markdown": "# First", "error": None,
        "cached": False, "fetched_at": None,
    })
    session = _FakeSession(cookies=[])
    session.pages = {
        live_url: _FakePage(live_url, "Second – Medium", _full_article_html("Second")),
    }
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    results = fetch.fetch_articles([cached_url, live_url], cookies=[])

    assert [r.url for r in results] == [cached_url, live_url]
    assert results[0].cached is True
    assert results[1].cached is False
    assert session.enter_count == 1


def test_fetch_articles_writes_full_results_back_to_cache(monkeypatch):
    from mediumlm import cache as cache_mod

    url = "https://medium.com/@a/first-abc123abc123"
    session = _FakeSession(cookies=[])
    session.pages = {url: _FakePage(url, "First – Medium", _full_article_html("First"))}
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    fetch.fetch_articles([url], cookies=[])

    entry = cache_mod.load_cached(url)
    assert entry is not None
    assert "First" in entry["markdown"]


def test_fetch_articles_use_cache_false_bypasses_reads_but_still_writes(monkeypatch):
    from mediumlm import cache as cache_mod

    url = "https://medium.com/@a/first-abc123abc123"
    cache_mod.store({
        "url": url, "title": "Stale – Medium", "access": "full",
        "access_reason": None, "markdown": "# Stale", "error": None,
        "cached": False, "fetched_at": None,
    })
    session = _FakeSession(cookies=[])
    session.pages = {url: _FakePage(url, "Fresh – Medium", _full_article_html("Fresh"))}
    monkeypatch.setattr(
        "mediumlm.browser.BrowserSession", lambda cookies, settle_ms=2000: session
    )

    results = fetch.fetch_articles([url], cookies=[], use_cache=False)

    assert results[0].cached is False
    assert "Fresh" in results[0].markdown
    assert "Fresh" in cache_mod.load_cached(url)["markdown"]  # written back
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python3 -m pytest tests/test_fetch.py -v`
Expected: the 4 new tests FAIL (`fetch_articles` has no cache behavior / no `use_cache` parameter / `ArticleResult` has no `cached` field); the 7 existing tests still PASS.

- [ ] **Step 3: Implement in `src/mediumlm/fetch.py`**

Add imports `import dataclasses` and `from . import cache as cache_mod`. Extend the dataclass:

```python
@dataclass
class ArticleResult:
    url: str
    title: str
    access: str
    access_reason: Optional[str]
    markdown: str
    error: Optional[str] = None
    cached: bool = False
    fetched_at: Optional[str] = None
```

Replace `fetch_articles` with (docstring: keep the existing teardown-suppression sentence, add cache semantics):

```python
def fetch_articles(
    urls: List[str],
    cookies: List[dict],
    use_cache: bool = True,
    cache_dir=None,
) -> List[ArticleResult]:
    """Fetch several articles, serving cache hits without a browser.

    The cache is consulted first (unless use_cache=False); a browser
    session is launched only when at least one URL misses. Full-access
    results are written back to the cache either way. Per-URL failures
    are recorded as `access: "error"` results and the batch continues.
    Teardown failures are suppressed so already-fetched results always
    reach the caller. Results preserve input order.
    """
    results: List[Optional[ArticleResult]] = [None] * len(urls)
    misses: List[int] = []
    for i, url in enumerate(urls):
        entry = cache_mod.load_cached(url, cache_dir=cache_dir) if use_cache else None
        if entry is not None:
            results[i] = ArticleResult(
                url=url,
                title=entry.get("title", ""),
                access="full",
                access_reason=None,
                markdown=entry.get("markdown", ""),
                cached=True,
                fetched_at=entry.get("fetched_at"),
            )
        else:
            misses.append(i)

    if misses:
        session = browser_mod.BrowserSession(cookies)
        session.__enter__()
        try:
            for i in misses:
                url = urls[i]
                try:
                    page = session.fetch(url)
                    access, reason = parsing.detect_access(
                        page.html, page.title, status=page.status
                    )
                    result = ArticleResult(
                        url=url,
                        title=page.title,
                        access=access,
                        access_reason=reason,
                        markdown=parsing.extract_article_markdown(page.html),
                    )
                except Exception as exc:
                    result = ArticleResult(
                        url=url,
                        title="",
                        access="error",
                        access_reason=None,
                        markdown="",
                        error=str(exc),
                    )
                cache_mod.store(dataclasses.asdict(result), cache_dir=cache_dir)
                results[i] = result
        finally:
            try:
                session.__exit__(None, None, None)
            except Exception:
                # Teardown failure must not discard already-fetched
                # results; the OS reaps the crashed browser process.
                pass
    return [r for r in results if r is not None]
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/ -q`
Expected: 68 passed (64 + 4). The pre-existing fetch/CLI tests pass unchanged because the autouse fixture isolates the cache directory and `store` rejects their non-full fakes silently.

- [ ] **Step 5: Commit**

```bash
git add src/mediumlm/fetch.py tests/test_fetch.py
git commit -m "feat: fetch consults article cache, launches browser only on misses"
```

---

## Task 4: CLI — `--no-cache` and `cache` subcommands

**Files:**
- Modify: `src/mediumlm/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add the autouse fixture and failing tests to `tests/test_cli.py`**

At the top (after imports; add `import pytest` if missing):

```python
@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("mediumlm.cache.DEFAULT_CACHE_DIR", tmp_path / "cache")
```

Update every existing monkeypatched `fetch_articles` fake in this file (the batch-fetch tests and the auto-refresh tests) to accept the new keywords: change `lambda urls, cookies: ...` to `lambda urls, cookies, use_cache=True, cache_dir=None: ...` and `def fake_fetch_articles(urls, cookies):` to `def fake_fetch_articles(urls, cookies, use_cache=True, cache_dir=None):`. Behavior unchanged — only signatures widen.

Append:

```python
def test_fetch_no_cache_flag_threads_use_cache_false(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    captured_kwargs = {}

    def fake_fetch_articles(urls, cookies, use_cache=True, cache_dir=None):
        captured_kwargs["use_cache"] = use_cache
        return [ArticleResult(url=urls[0], title="T", access="full",
                              access_reason=None, markdown="# T")]

    monkeypatch.setattr("mediumlm.fetch.fetch_articles", fake_fetch_articles)

    exit_code = cli.main([
        "fetch", "https://medium.com/@a/x-abc123abc123",
        "--no-cache", "--path", str(cookie_path),
    ])

    assert exit_code == 0
    assert captured_kwargs["use_cache"] is False


def test_fetch_json_includes_cached_field(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
            ArticleResult(url=urls[0], title="T", access="full", access_reason=None,
                          markdown="# T", cached=True, fetched_at="2026-07-22T00:00:00+00:00")
        ],
    )

    exit_code = cli.main(
        ["fetch", "https://medium.com/@a/x-abc123abc123", "--path", str(cookie_path)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cached"] is True
    assert payload["fetched_at"] == "2026-07-22T00:00:00+00:00"


def test_cache_list_prints_entries(capsys):
    from mediumlm import cache as cache_mod

    cache_mod.store({
        "url": "https://medium.com/@a/x-abc123abc123", "title": "X", "access": "full",
        "access_reason": None, "markdown": "# X", "error": None,
        "cached": False, "fetched_at": None,
    })

    exit_code = cli.main(["cache", "list"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["url"] == "https://medium.com/@a/x-abc123abc123"
    assert payload[0]["title"] == "X"


def test_cache_clear_all_and_single(capsys):
    from mediumlm import cache as cache_mod

    for slug, title in [("x-abc123abc123", "X"), ("y-def456def456", "Y")]:
        cache_mod.store({
            "url": f"https://medium.com/@a/{slug}", "title": title, "access": "full",
            "access_reason": None, "markdown": "#", "error": None,
            "cached": False, "fetched_at": None,
        })

    exit_code = cli.main(["cache", "clear", "--url", "https://medium.com/@a/x-abc123abc123"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"cleared": 1}

    exit_code = cli.main(["cache", "clear"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"cleared": 1}


def test_cache_clear_containment_error_reports_and_exits_1(monkeypatch, capsys):
    from mediumlm import cache as cache_mod

    cache_mod.store({
        "url": "https://medium.com/@a/x-abc123abc123", "title": "X", "access": "full",
        "access_reason": None, "markdown": "#", "error": None,
        "cached": False, "fetched_at": None,
    })
    monkeypatch.setattr("mediumlm.cache.cache_key", lambda url: "../../evil")

    exit_code = cli.main(["cache", "clear", "--url", "https://medium.com/@a/x-abc123abc123"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing to delete" in captured.err
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: the 5 new tests FAIL (`--no-cache` unrecognized; `cache` subcommand missing); the 15 existing tests PASS — because their `fetch_articles` fakes were widened to accept `use_cache`/`cache_dir` in Step 1, so `_cmd_fetch`'s not-yet-added `use_cache=` call doesn't raise TypeError against them.

- [ ] **Step 3: Implement in `src/mediumlm/cli.py`**

Add import `from . import cache as cache_mod`. In `_cmd_fetch`, change the fetch call to thread the flag:

```python
    results = fetch_mod.fetch_articles(
        args.urls, cookies=loaded, use_cache=not args.no_cache
    )
```

and the auto-refresh retry call likewise (cache hits cannot be expired, so the flag value is inert there — pass it anyway for uniformity):

```python
                retried = fetch_mod.fetch_articles(
                    [args.urls[i] for i in expired],
                    cookies=reloaded,
                    use_cache=not args.no_cache,
                )
```

Add the two cache command handlers after `_cmd_fetch`:

```python
def _cmd_cache_list(args: argparse.Namespace) -> int:
    print(json.dumps(cache_mod.list_entries()))
    return 0


def _cmd_cache_clear(args: argparse.Namespace) -> int:
    try:
        removed = cache_mod.clear(url=args.url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"cleared": removed}))
    return 0
```

In `build_parser`, add to the fetch subparser (next to `--no-refresh`):

```python
    fetch_parser.add_argument(
        "--no-cache", action="store_true",
        help="bypass the article cache (fresh results are still written back)",
    )
```

and register the cache subcommand after the fetch parser:

```python
    cache_parser = sub.add_parser("cache")
    cache_sub = cache_parser.add_subparsers(dest="cache_command", required=True)

    cache_list_parser = cache_sub.add_parser("list")
    cache_list_parser.set_defaults(func=_cmd_cache_list)

    cache_clear_parser = cache_sub.add_parser("clear")
    cache_clear_parser.add_argument("--url")
    cache_clear_parser.set_defaults(func=_cmd_cache_clear)
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: 73 passed (68 + 5).

- [ ] **Step 5: Commit**

```bash
git add src/mediumlm/cli.py tests/test_cli.py
git commit -m "feat: --no-cache flag and cache list/clear subcommands"
```

---

## Task 5: Docs, skill vault workflow, live verification, release

**Files:**
- Modify: `README.md`
- Modify: `~/.claude/skills/mediumlm/SKILL.md` (outside the repo — edited, never committed here)
- Modify: `pyproject.toml` (version bump)

- [ ] **Step 1: README updates**

In the Usage section, after the batch-fetch example, add:

```bash
# Repeat fetches are served from ~/.mediumlm/cache (marked
# "cached": true in the JSON); only full-access articles are cached,
# so previews and errors always retry. --no-cache forces a refetch.
mediumlm cache list                 # what's cached: [{url, title, fetched_at}]
mediumlm cache clear --url <url>    # drop one entry (omit --url for all)
```

In the Security section's cookie bullet list, add a bullet: the article cache (`~/.mediumlm/cache/`, created `0700`) stores full text of member-only articles you fetched — private content; `cache clear` wipes it and refuses to delete outside its own directory.

- [ ] **Step 2: SKILL.md vault-corpus workflow**

Edit `~/.claude/skills/mediumlm/SKILL.md` per the spec's §4 (match existing tone/width):
- In Workflow step 3 (Fetch): note that results may carry `"cached": true` + `fetched_at` — cached articles are full-access copies from an earlier run; treat them identically to live results, and mention `--no-cache` if the user explicitly wants a refetch.
- Replace the "Saved research note" bullet in step 4 with the vault corpus: article notes at `/Users/pisitkoolplukpol/Documents/Obsidian Vault/Research/Medium/Articles/<slug>.md` (frontmatter `type: article`, `url`, `author`, `source: medium`, `fetched`, `topics:` quoted-wikilink list; ~10-line curated summary + key excerpts; if the note exists, only append the topic to `topics:`); topic hubs at `Research/Medium/<topic-slug>.md` (frontmatter `type: research-topic`, `status: active`, `created`, `updated`; synthesized answer + Sources section of wikilinks with access labels; re-runs update in place, never dated duplicates); one line per hub in `Research/Medium MOC.md`. All vault writes delegated to Sonnet agents. The old `docs/research/medium/` flat files are no longer created.

- [ ] **Step 3: Version bump**

In `pyproject.toml`: `version = "0.2.0"` → `version = "0.3.0"`.

```bash
git add README.md pyproject.toml
git commit -m "docs: cache usage + security notes; bump version to 0.3.0"
```

- [ ] **Step 4: Reinstall and live verification**

```bash
uv tool install --reinstall /Users/pisitkoolplukpol/Work/mediumlm
mediumlm cache clear
time mediumlm fetch "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['access'], d['cached'])"
time mediumlm fetch "https://medium.com/@mdanassaif/i-connected-these-7-mcps-to-claude-im-never-going-back-b9f433b82a5b" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['access'], d['cached'], d['fetched_at'])"
mediumlm cache list
```
Expected: first run `full False` (seconds); second run `full True` + timestamp, near-instant (<1s, no browser); `cache list` shows the entry. Then a batch mixing the cached URL with a fresh one: array order preserved, first `cached: true`, second `cached: false`.

- [ ] **Step 5: Vault manual verification (skill-side)**

Run a real `/mediumlm` topic with 2 articles; confirm: `Research/Medium/Articles/` gains 2 notes with correct frontmatter, topic hub created with Sources wikilinks, MOC line added. Re-run the topic adding 1 new article: no duplicate article notes, hub updated in place (`updated` bumped, new source appended), shared articles' `topics:` lists appended.

- [ ] **Step 6: Merge, push, tag**

```bash
cd /Users/pisitkoolplukpol/Work/mediumlm
git checkout main && git merge --ff-only article-cache
git push origin main
git tag -a v0.3.0 -m "v0.3.0: article cache (full-only, atomic, indexed), --no-cache, cache list/clear, vault-corpus skill workflow"
git push origin --tags
git branch -d article-cache
uv tool install --reinstall /Users/pisitkoolplukpol/Work/mediumlm
```
