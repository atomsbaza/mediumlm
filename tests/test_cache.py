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


def test_store_with_unserializable_value_fails_soft_and_leaves_no_temp_files(capsys):
    bad = dict(_full_result(), markdown=set())
    assert cache.store(bad) is False
    assert "cache write failed" in capsys.readouterr().err
    assert list(cache.DEFAULT_CACHE_DIR.glob(".tmp-*")) == []


def test_store_returns_true_when_index_write_fails(capsys):
    cache.store(_full_result())
    (cache.DEFAULT_CACHE_DIR / "index.json").unlink()
    (cache.DEFAULT_CACHE_DIR / "index.json").mkdir(parents=True)
    assert cache.store(_full_result(url="https://medium.com/@b/y-def456def456", title="Y")) is True
    assert "index" in capsys.readouterr().err
    assert cache.load_cached("https://medium.com/@b/y-def456def456") is not None
