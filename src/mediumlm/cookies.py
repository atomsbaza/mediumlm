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
