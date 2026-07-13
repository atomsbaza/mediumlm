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
     `docs/research/medium/<topic-slug>-<YYYY-MM-DD>.md` (in the
     *calling* project, not the mediumlm repo), containing: the list of
     sources with URLs, key excerpts/quotes, and the synthesized summary.
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

## Open Questions

None blocking implementation. The Medium search endpoint (GraphQL vs.
fallback) will be resolved during implementation and does not change the
external CLI contract either way.
