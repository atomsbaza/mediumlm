# mediumlm

Research a topic on Medium using your own logged-in Medium session —
without needing an interactive browser at request time. Extracts your
Medium session cookies from Chrome once, then uses a headless browser
to search Medium and fetch full article text (including member-only
content your account can access).

Built as the engine behind a Claude Code skill
(`~/.claude/skills/mediumlm/SKILL.md`, installed separately, outside
this repo), but the `mediumlm` CLI works standalone from any terminal.

## Install

```bash
uv tool install .          # installs the `mediumlm` CLI into ~/.local/bin
python3 -m playwright install chromium
```

After changing the source, refresh with `uv tool install --reinstall .`.
For a dev/editable install for hacking on the code, use
`pip3 install -e ".[dev]"`.

Requires Python 3.9+ and Chrome, logged into Medium, for the first
cookie extraction.

## Usage

```bash
# Extract your Medium session cookies from Chrome (run once, and
# again whenever the session goes stale)
mediumlm cookies extract

# Confirm the stored session still authenticates
mediumlm cookies check

# Search Medium for a topic (Medium currently blocks this for
# headless clients; the command fails with a clear error pointing
# at the fallback — see "How it works" below)
mediumlm search "claude code mcp" --limit 8

# Fetch a specific article's full text using your session
mediumlm fetch "https://medium.com/@author/article-slug-abc123abc123"
```

Every command prints a single JSON object/array to stdout on success.
On failure, stdout is empty, an `error: <message>` line goes to
stderr, and the exit code is `1`.

`fetch`'s output includes an explicit `access: "full" | "preview"`
field with an `access_reason` (`blocked`, `cookies_expired`, or
`not_member`) whenever the article wasn't fully readable — this is
never silently collapsed into a plain success.

## How it works

- **Cookies** are extracted from Chrome's local cookie store
  (`browser_cookie3`) and stored at `~/.mediumlm/cookies.json` with
  `0600` permissions — this file is a bearer-token-equivalent secret
  for your Medium session; never commit it or share it.
- **Fetching an article** uses a headless Playwright browser with your
  cookies injected. A plain HTTP client doesn't work here — Medium's
  Cloudflare bot detection blocks it; a real (headless) browser
  context does not trip the same defenses.
- **Searching** is currently unavailable. A 2026-07-15 finding showed
  unauthenticated search working while authenticated search was
  blocked; that was superseded on 2026-07-19 — Medium's search-results
  GraphQL API now returns 403 to headless-browser XHRs regardless of
  whether cookies are sent, and the page renders an error state instead
  of results. `mediumlm search` detects this and raises a clear
  "search unavailable" error (exit 1) rather than returning junk; it
  still returns a genuine empty list for real zero-result queries if
  search ever works again. The practical discovery path in the
  meantime is an external web search restricted to `site:medium.com`,
  feeding the found URLs to `mediumlm fetch` (which still works fully
  with your session). The search code path stays in place so `search`
  resumes working automatically if Medium unblocks it.

See `docs/superpowers/specs/2026-07-14-mediumlm-design.md` for the
full design rationale, including the live-verification findings above.

## Scope

Built for personal research against your own Medium account, at
normal single-topic, on-demand volume. Automated access likely falls
outside Medium's Terms of Service; this is not a bulk-scraping tool.

## Development

```bash
python3 -m pytest tests/ -v
```

39 tests, all fixture/mock-driven except one that drives a real local
HTTP server to verify cookie injection actually reaches the browser
layer.
