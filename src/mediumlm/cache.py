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
        try:
            index = _read_json(directory / INDEX_NAME) or {}
            index[normalized] = {
                "title": entry.get("title", ""),
                "fetched_at": entry["fetched_at"],
                "file": entry_name,
            }
            _atomic_write(directory / INDEX_NAME, index)
        except (OSError, TypeError, ValueError) as exc:
            _note(f"cache index update failed ({exc}); entry cached but may not appear in cache list")
        return True
    except (OSError, TypeError, ValueError) as exc:
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
