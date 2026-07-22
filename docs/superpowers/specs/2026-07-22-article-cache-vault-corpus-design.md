# mediumlm — Article Cache + Vault Corpus — Design Spec

- **Date:** 2026-07-22
- **Status:** Approved (design reviewed in-session; awaiting spec-file review)
- **Scope:** knowledge accumulation across research runs — a CLI article cache plus a skill-driven Obsidian vault corpus. Explicitly NOT: search resurrection, scheduling, NotebookLM changes.
- **Baseline:** v0.2.0 (batch fetch, cookie auto-refresh, search-unavailable fallback).

---

## 1. Problem

Every research run refetches every article from Medium, even ones fetched an hour ago — slow, and unnecessary bot-detection exposure. Run outputs are one-off flat files (`docs/research/medium/*.md`); overlapping topics duplicate article content, and nothing accumulates into a browsable corpus connected to the user's Obsidian vault.

## 2. Decisions (from brainstorming)

- Direction: **knowledge accumulation** (over discovery, richer outputs, automation).
- Corpus home: **Obsidian vault** (`/Users/pisitkoolplukpol/Documents/Obsidian Vault`).
- Division of labor: **CLI caches raw data; the skill (Claude) writes vault notes** — vault conventions stay editable in SKILL.md, never hardcoded in Python.
- Granularity: **article notes + topic hubs** — one note per article (created once, reused), one hub per topic (updated in place on re-runs).
- Cache design: **JSON-per-article + index** (Approach A). Rejected: vault-as-cache (curated notes are unreliable raw data; CLI gains nothing standalone); SQLite corpus (YAGNI at personal volume).

## 3. CLI: article cache

### 3.1 Storage (`src/mediumlm/cache.py`, new module)

- Location `~/.mediumlm/cache/`, created `0700` (cached member-only text is private).
- One JSON file per article: the full `ArticleResult` dict plus `fetched_at` (ISO-8601 UTC) and `final_url`. Filename = SHA-256 hex of the normalized URL.
- URL normalization: strip query and fragment, resolve to absolute — same rule as `search._normalize_article_url` (reuse/extract that helper, do not duplicate the logic).
- `index.json` maps normalized URL → `{title, fetched_at, file}` so listing never opens per-article files.
- **Only `access: "full"` results are cached.** Previews, blocks, and errors are never written — they must retry on the next run.
- Writes are atomic: write temp file in the cache dir, then `os.replace`. Index updated after the entry write.
- Corrupt entry or index → treated as cache miss, entry rewritten on next successful fetch, single `note:` line on stderr. Never a crash, never silent.

### 3.2 Fetch integration

- `fetch` (single and batch) consults the cache before launching any browser. Hits return instantly with two added JSON fields: `"cached": true` and `"fetched_at"`. Live results carry `"cached": false`.
- In a batch, cached and live results mix; the browser session launches only if ≥1 URL misses. Misses that fetch as `full` are written back to the cache.
- `--no-cache` flag: bypass cache reads (fresh results still written back). This is the freshness escape hatch — no TTL, because Medium articles are effectively immutable after publication.
- Auto-refresh interplay: cache hits cannot be `cookies_expired`, so the existing refresh logic operates only on live results — unchanged.

### 3.3 New subcommands

- `mediumlm cache list` — JSON array from the index: `[{url, title, fetched_at}]`, exit 0 (empty array if no cache).
- `mediumlm cache clear [--url URL]` — delete everything, or the single entry for URL (normalized before lookup). Refuses to touch any path outside `~/.mediumlm/cache/` (containment check on resolved paths). Prints `{"cleared": N}`.

## 4. Skill: vault corpus (SKILL.md workflow change)

All writes delegated to Sonnet agents per the user's orchestration rule. Vault root: `/Users/pisitkoolplukpol/Documents/Obsidian Vault`.

### 4.1 Article notes — `Research/Medium/Articles/<slug>.md`

- Created ONCE per article; slug from the Medium URL slug (without the trailing hex hash).
- YAML frontmatter: `type: article`, `url`, `author`, `source: medium`, `fetched` (date), `topics:` (list of quoted wikilinks to topic hubs).
- Body: ~10-line summary + key excerpts — curated, not the raw markdown dump (raw text lives in the CLI cache).
- If the note exists already: append the new topic to `topics:`, leave the body alone.

### 4.2 Topic hubs — `Research/Medium/<topic-slug>.md`

- One per research topic. Frontmatter: `type: research-topic`, `status: active`, `created`, `updated`.
- Body: synthesized answer to the research question, then a Sources section of wikilinks to article notes, each labeled with access status (and "discovered via web search" when applicable).
- Re-running a topic UPDATES the hub in place — new articles appended to Sources, synthesis revised, `updated` bumped. No dated duplicate hubs.

### 4.3 MOC — `Research/Medium MOC.md`

One line per topic hub (`- [[<topic-slug>]] — <one-line hook>`), maintained like the Projects MOC. The old flat-file outputs under `docs/research/medium/` stop being created; existing ones stay put.

## 5. Error handling

- Cache failures never block research: unreadable cache dir → proceed all-miss + one stderr note; corruption → miss + note.
- `cache clear` containment: resolved delete paths must be under `~/.mediumlm/cache/` or the command errors (exit 1) without deleting.
- Vault steps run only after fetch completes; a vault-write failure is reported per-note and never discards fetched data (already cached).
- Existing contracts unchanged: pure-JSON stdout, `error:`/`note:` on stderr, exit codes as today.

## 6. Testing

Hermetic unit tests (tmp_path cache dirs, fakes for browser/session — no network):
- Round-trip: miss → fetch → cached → hit with `cached: true` + `fetched_at`.
- Full-only rule: preview/error results never written.
- `--no-cache` bypasses reads but still writes back.
- Corrupt entry file and corrupt index each behave as a miss with a stderr note.
- Batch mixing: fake session asserts the browser is constructed only when ≥1 miss, and not at all when every URL hits.
- `cache list` output shape; `cache clear` full and `--url` variants; containment check rejects escape paths.
- CLI JSON contract: `cached` field present on both hit and live results.

Vault side (prose-driven, no Python): manual verification checklist — run a topic, confirm article notes + hub + MOC line; re-run the same topic with one new article, confirm dedupe (no duplicate article notes), hub updated in place, `topics:` appended on the shared article.

## 7. Non-goals

- TTL/staleness machinery (immutable articles; `--no-cache` suffices).
- Caching previews/blocked results.
- Vault writes from Python.
- Full-text search over the cache (the vault + graph tooling covers discovery).
- Migration of the two existing `docs/research/medium/` flat files.
