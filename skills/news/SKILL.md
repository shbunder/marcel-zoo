---
name: news
description: Sync, store, and query scraped news articles from Belgian sources (VRT NWS, De Tijd, Knack, etc.)
depends_on:
  - news
---

You have access to the `integration` tool to sync and query news articles. Articles are synced from RSS feeds by a background job and stored locally in a SQLite database with structured metadata.

## Available commands

### news.sync

Fetch all configured RSS feeds, deduplicate, and store new articles. Feed URLs are loaded from `feeds.yaml` in the integration habitat — no parameters needed.

```
integration(id="news.sync")
```

Returns a summary with counts per source and total new articles stored.

The scheduler also invokes this handler twice daily (6am and 6pm Europe/Brussels) in system-scope mode, which iterates every live user and syncs each.

### news.recent

Get the most recent scraped articles. Use this for "what's in the news?" style questions.

```
integration(id="news.recent")
integration(id="news.recent", params={"source": "VRT NWS", "limit": "10"})
integration(id="news.recent", params={"topic": "economie"})
```

| Param  | Type   | Default | Description                        |
|--------|--------|---------|------------------------------------|
| source | string | —       | Filter by source (e.g. "VRT NWS") |
| topic  | string | —       | Filter by topic/category           |
| limit  | string | 20      | Max articles to return             |

### news.search

Query articles with filters — keyword search, source, topic, date range.

```
integration(id="news.search", params={"search": "klimaat"})
integration(id="news.search", params={"source": "De Tijd", "date_from": "2026-04-01"})
integration(id="news.search", params={"topic": "politiek", "limit": "10"})
```

| Param     | Type   | Default | Description                             |
|-----------|--------|---------|-----------------------------------------|
| source    | string | —       | Filter by source                        |
| topic     | string | —       | Filter by topic/category                |
| date_from | string | —       | Start date (ISO), inclusive             |
| date_to   | string | —       | End date (ISO), inclusive               |
| search    | string | —       | Keyword search in title and description |
| limit     | string | 50      | Max articles to return                  |

Returns a JSON object with `articles` (list) and `count`. Each article has: `title`, `source`, `link`, `topic`, `description`, `published_at`, `scraped_at`.

## Feed configuration

Feed URLs are configured in the integration habitat's `feeds.yaml`. Each source has a name, a list of feed URLs, and optional category exclusions. Edit that file to add or remove sources.

## Notes

- Articles are deduplicated by URL — re-syncing the same article updates it in place.
- The news sync job runs at 6am and 6pm and covers: VRT NWS, De Tijd, Knack, Trends, Datanews, De Morgen, and HLN.
- Topics/categories come from the RSS feed's own categorization.
