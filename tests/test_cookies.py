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


def test_check_cookies_detects_non_200_status(tmp_path, monkeypatch):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(json.dumps(
        [{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/", "secure": True}]
    ))

    class FakePage:
        status = 403
        final_url = "https://medium.com/me/settings"
        title = "Just a moment..."
        html = "<html></html>"

    monkeypatch.setattr("mediumlm.browser.fetch_page", lambda url, cookies: FakePage())

    result = cookies.check_cookies(path=cookie_path)

    assert result["authenticated"] is False


def test_check_cookies_missing_file_raises(tmp_path):
    with pytest.raises(cookies.CookiesNotFoundError):
        cookies.check_cookies(path=tmp_path / "nope.json")
