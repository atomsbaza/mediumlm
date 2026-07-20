import json

from mediumlm import cli
from mediumlm.search import SearchResult, SearchUnavailableError


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
