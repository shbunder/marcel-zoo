# news (park)

Belgian news aggregator. Fetches RSS feeds on a schedule, deduplicates by
URL, and stores articles in a per-user SQLite cache that the agent can
query by source, topic, date range, or keyword.

Spans two habitats:

- [integrations/news/](.) — handlers, cache, sync logic, feed config
- [skills/news/](../../skills/news/) — `SKILL.md` / `SETUP.md` that teach
  the agent when to use the handlers

## Handlers

Registered via `@register(...)` in [__init__.py](__init__.py):

| ID            | Purpose                                                         |
|---------------|-----------------------------------------------------------------|
| `news.sync`   | Fetch every configured feed, dedupe, upsert new rows            |
| `news.recent` | Return the most recent cached articles                          |
| `news.search` | Query cached articles by source / topic / date range / keyword  |

All three are async and return JSON strings the agent can quote back.

## Scheduled sync

[integration.yaml](integration.yaml) declares a `scheduled_jobs:` entry so
the kernel's scheduler runs `news.sync` twice a day (06:00 and 18:00
`Europe/Brussels`). The scheduler invokes the handler with the sentinel
slug `_system`, which triggers fan-out: the handler iterates every live
user directory under `users/` and syncs each one. A direct call with a
real `user_slug` (e.g. through the `integration` tool) syncs only that
user.

Backup snapshots (`*.backup-<n>`) and the `_system` sentinel itself are
filtered out of the fan-out list — see `_live_user_slugs` in
[__init__.py](__init__.py).

On-failure notification goes to the `telegram` channel.

## Storage

[cache.py](cache.py) owns a SQLite database per user at
`<cache_dir>/news.db` (resolved via `marcel_core.plugin.paths.cache_dir`).
Schema lives in `_ensure_schema` and is created on first connect.
`journal_mode=WAL` is enabled so the twice-daily sync doesn't block
concurrent reads.

Articles are keyed by a 16-char SHA-256 prefix of the article URL
(`article_id`). Re-syncing the same URL updates the row in place rather
than inserting a duplicate.

## Feeds

[feeds.yaml](feeds.yaml) is the full list of sources. Each entry has:

```yaml
- name: <display name>          # used as the article's "source" field
  feeds: [<rss url>, ...]       # one or more feed URLs
  exclude_categories: [...]     # optional, case-insensitive
```

Edit this file to add, remove, or reconfigure sources — the next
`news.sync` picks the changes up automatically, no restart needed.

Current sources: VRT NWS, De Tijd, Knack, Trends, Datanews, De Morgen,
HLN.

## Sync flow

[sync.py](sync.py) is the worker:

1. Load [feeds.yaml](feeds.yaml).
2. Kick off one `asyncio.Task` per `(source, feed_url)` pair, fanning out
   with `marcel_core.plugin.rss.fetch_feed`.
3. Swallow per-feed fetch errors as warnings — a dead feed never fails
   the whole sync.
4. Apply `exclude_categories`, annotate each article with its source
   name, rename RSS `category` → `topic`.
5. Deduplicate by link within the batch, then call
   `filter_new_links` to drop anything already stored.
6. `upsert_articles` writes what remains and returns the count.

Returns a summary dict: `{new, total_fetched, unique, sources: [...]}`.

## Tests

[tests/](tests/) is discovered by the root [pytest.ini](../../pytest.ini).

```bash
pytest integrations/news/
```

The test loader synthesizes a parent package for `cache.py` and `sync.py`
so their `from .cache import …` relative imports resolve without
triggering `@register` decorators on import — see the module docstring
in [tests/test_news.py](tests/test_news.py) for the mechanism.

## Requirements

None beyond `MARCEL_ZOO_DIR` pointing at this repo — no credentials, no
external accounts. `integration.yaml` declares `requires: {}`.
