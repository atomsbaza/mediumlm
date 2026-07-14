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
