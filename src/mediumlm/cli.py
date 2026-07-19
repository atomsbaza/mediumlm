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
    try:
        results = search_mod.search(args.query, cookies=loaded, limit=args.limit)
    except search_mod.SearchUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
    extract_parser.add_argument("--browser", default="chrome", choices=["chrome"])
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
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
