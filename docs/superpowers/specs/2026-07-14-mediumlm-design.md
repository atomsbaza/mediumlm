# mediumlm — Design Spec

Date: 2026-07-14

## Summary

A Claude Code skill that lets you research a topic on Medium using your own
logged-in Medium session, without requiring an interactive/unlocked browser
at query time. Given a topic, it searches Medium, fetches full article text
(including member-only content your account can access), and produces:
a synthesized chat answer, a saved research note, and — on request — deeper
artifacts (audio overview, mind map, study guide) via the existing
`notebooklm` skill.

## Motivation

The user wants Claude to be able to read/research a topic sourced from
Medium, including paywalled content they have access to via their own
Medium membership, and wants this to work even when their MacBook is
locked (so it can't depend on live, interactive browser automation at
request time).

**Clarifying what "works while locked" actually means:** the request must
still be *issued* while the machine is unlocked and Claude Code has an
active session — there is no way to send Claude a prompt on a locked
screen. What "on-demand only" + "works while locked" together guarantee is
that the *run itself*, once started, needs no interactive browser and no
unlocked screen to complete — e.g. you kick off a research request, then
lock your machine, and it finishes unattended. It is not a scheduled/
autonomous trigger (see Non-goals) and it cannot be started from a locked
screen.

## Non-goals

- Not a general web scraper — scoped to medium.com only.
- Not a replacement for NotebookLM's own artifact generation — it feeds
  NotebookLM rather than reimplementing podcast/mind-map generation.
- Not scheduled/autonomous (no cron-driven background research) — this
  version is on-demand only. Designed so scheduling could be added later
  without rework, but not built now.

## Architecture

Two pieces:

1. **Project repo** — `/Users/pisitkoolplukpol/Work/mediumlm/` — a Python
   package containing the `mediumlm` CLI and its tests. This is where all
   development happens.
2. **Skill** — `~/.claude/skills/mediumlm/SKILL.md` — tells Claude when
   and how to invoke the CLI from the project repo. The skill is a thin
   wrapper; no logic lives in the skill directory itself.

This mirrors the existing `notebooklm` skill's split between "skill
instructions" and "the actual tool."

## Components

### `mediumlm cookies extract [--browser chrome]`
Pulls Medium-domain cookies out of the local Chrome cookie store (via
`browser_cookie3` or `rookiepy`, the same technique `notebooklm-py` uses
for `--browser-cookies`). Writes them to `~/.mediumlm/cookies.json`.
Run manually whenever Medium logs the session out or rotates cookies.

**Secret handling (required, not optional):**
- The file is written with `0600` permissions — it is a bearer-token-
  equivalent secret (session hijack risk if leaked), not casual config.
- `cookies extract` refuses to write into any path under a git-tracked
  directory (checks for a `.git` in an ancestor of the target path) and
  errors out instead, telling the user to point `--path` somewhere
  untracked. Default path (`~/.mediumlm/`) is outside any repo, so this
  only matters if the default is overridden.
- The `mediumlm` project repo's `.gitignore` excludes the default cookie
  directory pattern, build artifacts, and virtualenvs from the start —
  before any code lands, not retrofitted after a near-miss commit.

### `mediumlm cookies check`
Makes a real request to a logged-in-only Medium endpoint (e.g. the
account/profile page) to confirm the stored cookies still authenticate.
Distinguishes "no cookie file" from "cookie file present but stale" in
its error message.

### `mediumlm search <query> [--limit N]`
Uses the stored session to search Medium for the query. Returns a JSON
list of candidates: `{title, url, author, publication, snippet}`.

Primary approach: Medium's internal search/GraphQL endpoint (surfaces
personalized results, including from publications the user follows).

**Open risk:** Medium's search UI is a client-rendered React app; a plain
authenticated GET to the search page may not return results in raw HTML.
Implementation will need to identify the actual data endpoint (likely a
GraphQL call the SPA makes). If that endpoint proves unstable, blocked,
or requires additional signing, the documented fallback is: use
`WebSearch` with `site:medium.com`, then `mediumlm fetch` each result URL
for full text. This fallback trades personalization for reliability and
should be wired in from the start as a backstop, not added later in a
panic.

### `mediumlm fetch <url>`
Fetches the article HTML using the stored session, extracts clean
article text (readability/trafilatura-style extraction), and returns:
- markdown of the article body
- metadata (title, author, publication, published date)
- an explicit `access: "full" | "preview"` flag — if the returned content
  looks truncated/paywalled even with cookies attached (e.g. the account
  isn't a Medium member, or cookies are for a different account), this
  must be flagged rather than silently returned as if it were the full
  article.
- an `access_reason` string when not `"full"` — distinguishes "cookies
  expired," "account isn't a member," and "response looks like a bot
  challenge/block page," since all three currently collapse into the same
  observable "preview" state and are not actionable the same way.

**Core feasibility is not yet proven — spike before implementation.**
This design assumes cookies + a plain HTTP client (no browser engine) are
sufficient to retrieve full member-only article content. That is not
verified. Medium is a client-rendered React app with its own bot
detection, and `notebooklm-py` — the closest precedent in this codebase —
uses full Playwright browser automation for the analogous
authenticated-content problem, not raw cookies over HTTP. Before the
implementation plan is written, spike this end-to-end against one real
member-only Medium article:
1. `cookies extract`
2. a bare `httpx`/`requests` GET with those cookies against that URL
3. confirm the response contains the full article body, not a
   preview/paywall/challenge page

If the spike fails, this design's `fetch` component needs to move to a
headless-browser fetch (e.g. Playwright with the extracted cookies
injected into a browser context) instead of raw HTTP. That is still
compatible with "no interactive/unlocked screen required during the
run" — headless browsers don't need a display — so the rest of this
spec's data flow and outputs are unaffected either way; only the
internals of `fetch` change.

## Data Flow — `/mediumlm <topic>`

1. Claude runs `cookies check`. If it fails, Claude stops and tells the
   user to open Chrome, confirm they're logged into Medium, and run
   `mediumlm cookies extract` — it does not proceed with a stale session.
2. Claude runs `search <topic>` (default limit 8) and picks the most
   relevant results (or all, for a narrow topic).
3. Claude runs `fetch` for each selected article.
4. Claude produces all three outputs:
   - **Chat answer** — a synthesized summary/answer to the user's
     question, built directly from the fetched article text.
   - **Saved research note** — written to
     `docs/research/medium/<topic-slug>-<YYYY-MM-DD>.md`, containing: the
     list of sources with URLs, key excerpts/quotes, and the synthesized
     summary. Path resolution: if Claude is working inside a project that
     already has a `docs/` convention, the note goes there; otherwise it
     defaults to `~/Work/docs/research/medium/`. (No `docs/research/`
     convention exists anywhere in this workspace yet as of this spec —
     confirmed by checking `~/Work/docs/`, which only has
     `docs/superpowers/` — so this path will be created on first use, not
     appended to an existing one.)
   - **NotebookLM artifacts (on request only)** — if the user asks for a
     podcast/audio overview, mind map, or study guide, Claude adds the
     fetched sources into a NotebookLM notebook via the existing
     `notebooklm` skill and generates the requested artifact. Not run by
     default — only when explicitly asked, since it requires a NotebookLM
     login/browser session separate from the Medium cookie session.

## Error Handling

- **Stale/missing cookies**: explicit, actionable error
  ("run `mediumlm cookies extract`") — never silently treated as "no
  results."
- **Partial/paywalled access**: articles marked `access: "preview"` are
  clearly labeled as such in the chat answer and the saved note (e.g.
  "full text unavailable — preview only"), never blended in as if fully
  read.
- **Zero search results**: reported plainly to the user; no fabricated
  articles.
- **Rate limiting / CAPTCHA from Medium**: surfaced as an explicit error;
  no silent retry loop or exponential hammering.
- **Account-risk acknowledgment**: automated, cookie-based access to
  Medium likely falls outside Medium's Terms of Service. Repeated
  bot-like request patterns risk more than a single failed request — they
  risk the session being invalidated or the account being flagged/
  restricted. This tool is for personal research use against your own
  account, kept low-volume (single-topic, on-demand runs), not bulk
  scraping.

## Testing

Manual verification checklist (this tool talks to a live third-party
site, so unit tests are limited to the extraction/parsing logic, not
end-to-end Medium behavior):

- [ ] `mediumlm cookies extract` with Chrome open and logged into Medium
      → `~/.mediumlm/cookies.json` written with medium.com cookies
- [ ] `mediumlm cookies check` → reports authenticated
- [ ] `mediumlm search "some topic"` → returns real results with
      title/url/author
- [ ] `mediumlm fetch` on a known free article → markdown matches the
      article body
- [ ] `mediumlm fetch` on a known member-only article the account can
      access → `access: "full"`, complete text (not a truncated preview)
- [ ] `mediumlm fetch` on a member-only article simulating a
      non-member/expired session → `access: "preview"`, not silently
      treated as full text
- [ ] Delete `~/.mediumlm/cookies.json`, re-run any command → clear,
      actionable error, not a silent empty result

Unit tests (in the project repo) should cover: cookie-file
loading/validation logic, HTML-to-markdown extraction given saved sample
HTML fixtures, and the full/preview access-detection heuristic — these
don't require hitting real Medium and can run in CI.

## Open Questions — resolved

- **Fetch mechanism spike (2026-07-14): FAILED, mechanism revised.**
  Tested `cookies extract` (Chrome, via `browser_cookie3`) followed by a
  plain `requests.get(url, cookies=cj)` against a real member-only
  article. Result: HTTP `403`, body is a Cloudflare "Just a moment..."
  JS-challenge page, not article content — confirmed by grepping the
  response for `cloudflare`/`challenge` markers. Valid session cookies
  (`sid`, `uid`, `cf_clearance`, etc.) were present but insufficient;
  Medium/Cloudflare is evidently fingerprinting the client beyond
  cookies (TLS/JA3, HTTP/2 fingerprint, or similar), which a bare
  `requests` client cannot replicate.

  **Decision:** `fetch` (and likely `search`, same origin/protection)
  will use a headless Playwright browser context with the extracted
  cookies injected, rather than a plain HTTP client. This still
  satisfies "no interactive/unlocked screen required during the run" —
  headless browsers run without a display — so no other part of this
  spec's data flow or outputs changes. `cookies extract` is unaffected
  (it only reads Chrome's local cookie store, no network request). The
  Components section's `fetch`/`search` descriptions should be read as
  "via a headless browser session," not "via a plain HTTP client," when
  the implementation plan is written.

- Non-blocking, still open: the exact Medium search endpoint/approach
  (driving Medium's search UI directly in the headless browser vs. the
  documented `WebSearch` fallback) will be resolved during
  implementation and does not change the external CLI contract either
  way.
