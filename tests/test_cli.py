import json

import pytest

from mediumlm import cli
from mediumlm.search import SearchResult, SearchUnavailableError


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("mediumlm.cache.DEFAULT_CACHE_DIR", tmp_path / "cache")


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
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
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


def test_fetch_multiple_urls_prints_json_array(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
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
        lambda urls, cookies, use_cache=True, cache_dir=None: [
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
        lambda urls, cookies, use_cache=True, cache_dir=None: [
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


def test_search_unavailable_reports_websearch_fallback(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    monkeypatch.setattr(
        "mediumlm.search.search",
        lambda query, cookies, limit: (_ for _ in ()).throw(
            SearchUnavailableError(
                "Medium blocked the search-results API for query 'test topic' — "
                "fall back to WebSearch with 'site:medium.com test topic' and then "
                "`mediumlm fetch` each URL"
            )
        ),
    )

    exit_code = cli.main(["search", "test topic", "--path", str(cookie_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert "site:medium.com" in captured.err


def test_fetch_batch_partial_failure_exits_0_with_error_entries(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
            ArticleResult(url=urls[0], title="OK", access="full", access_reason=None, markdown="# OK"),
            ArticleResult(url=urls[1], title="", access="error",
                          access_reason=None, markdown="", error="net::ERR_TIMED_OUT"),
        ],
    )

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [p["access"] for p in payload] == ["full", "error"]
    assert captured.err == ""


def test_fetch_auto_refresh_retries_expired_urls(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    calls = []

    def fake_fetch_articles(urls, cookies, use_cache=True, cache_dir=None):
        calls.append(list(urls))
        if len(calls) == 1:
            return [
                ArticleResult(url=urls[0], title="OK", access="full",
                              access_reason=None, markdown="# OK"),
                ArticleResult(url=urls[1], title="", access="preview",
                              access_reason="cookies_expired", markdown=""),
            ]
        return [
            ArticleResult(url=urls[0], title="OK2", access="full",
                          access_reason=None, markdown="# OK2"),
        ]

    extract_calls = []

    def fake_extract_cookies(browser="chrome", path=None):
        extract_calls.append((browser, path))
        return [{"name": "sid", "value": "fresh", "domain": ".medium.com", "path": "/", "secure": True}]

    fresh_jar = [{"name": "sid", "value": "fresh", "domain": ".medium.com", "path": "/", "secure": True}]

    monkeypatch.setattr("mediumlm.fetch.fetch_articles", fake_fetch_articles)
    monkeypatch.setattr("mediumlm.cookies.extract_cookies", fake_extract_cookies)
    monkeypatch.setattr("mediumlm.cookies.load_cookies", lambda path=None: fresh_jar)

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [p["access"] for p in payload] == ["full", "full"]
    assert [p["url"] for p in payload] == [
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
    ]
    assert "re-extracted from Chrome" in captured.err
    assert len(extract_calls) == 1
    assert len(calls) == 2
    assert calls[1] == ["https://medium.com/@a/two-def456def456"]


def test_fetch_no_refresh_flag_disables_auto_refresh(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
            ArticleResult(url=urls[0], title="OK", access="full",
                          access_reason=None, markdown="# OK"),
            ArticleResult(url=urls[1], title="", access="preview",
                          access_reason="cookies_expired", markdown=""),
        ],
    )

    extract_calls = []
    monkeypatch.setattr(
        "mediumlm.cookies.extract_cookies",
        lambda browser="chrome", path=None: extract_calls.append((browser, path)),
    )

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
        "--no-refresh",
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload[1]["access"] == "preview"
    assert payload[1]["access_reason"] == "cookies_expired"
    assert extract_calls == []


def test_fetch_auto_refresh_failure_keeps_original_results(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    fetch_calls = []

    def fake_fetch_articles(urls, cookies, use_cache=True, cache_dir=None):
        fetch_calls.append(list(urls))
        return [
            ArticleResult(url=urls[0], title="OK", access="full",
                          access_reason=None, markdown="# OK"),
            ArticleResult(url=urls[1], title="", access="preview",
                          access_reason="cookies_expired", markdown=""),
        ]

    monkeypatch.setattr("mediumlm.fetch.fetch_articles", fake_fetch_articles)

    extract_calls = []

    def fake_extract_cookies(browser="chrome", path=None):
        extract_calls.append((browser, path))
        raise RuntimeError("keychain denied")

    monkeypatch.setattr("mediumlm.cookies.extract_cookies", fake_extract_cookies)

    exit_code = cli.main([
        "fetch",
        "https://medium.com/@a/one-abc123abc123",
        "https://medium.com/@a/two-def456def456",
        "--path", str(cookie_path),
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload[1]["access"] == "preview"
    assert payload[1]["access_reason"] == "cookies_expired"
    assert "automatic cookie refresh failed" in captured.err
    assert "keychain denied" in captured.err
    assert len(extract_calls) == 1
    assert len(fetch_calls) == 1


def test_fetch_auto_refresh_not_triggered_for_blocked(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    from mediumlm.fetch import ArticleResult

    monkeypatch.setattr(
        "mediumlm.fetch.fetch_articles",
        lambda urls, cookies, use_cache=True, cache_dir=None: [
            ArticleResult(url=urls[0], title="", access="preview",
                          access_reason="blocked", markdown=""),
        ],
    )

    extract_calls = []
    monkeypatch.setattr(
        "mediumlm.cookies.extract_cookies",
        lambda browser="chrome", path=None: extract_calls.append((browser, path)),
    )

    exit_code = cli.main(
        ["fetch", "https://medium.com/@a/one-abc123abc123", "--path", str(cookie_path)]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert extract_calls == []


def test_unexpected_exception_reports_as_clean_error(tmp_path, monkeypatch, capsys):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))
    monkeypatch.setattr(
        "mediumlm.search.search",
        lambda query, cookies, limit: (_ for _ in ()).throw(RuntimeError("browser crashed")),
    )

    exit_code = cli.main(["search", "test topic", "--path", str(cookie_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: browser crashed" in captured.err


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
