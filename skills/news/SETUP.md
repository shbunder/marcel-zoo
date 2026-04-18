---
name: news
description: Install the news habitat (no credentials needed)
---

The user is asking about news, but the news integration is not available.

## How to set up news

The news habitat has no credentials or external accounts — all it needs is the marcel-zoo directory on this install's `MARCEL_ZOO_DIR`.

### Steps

1. Make sure `MARCEL_ZOO_DIR` points at a marcel-zoo checkout in `.env.local`.
2. Confirm the news habitat is present:
   - `<MARCEL_ZOO_DIR>/integrations/news/integration.yaml`
   - `<MARCEL_ZOO_DIR>/skills/news/SKILL.md`
3. If you want to change which feeds are followed, edit
   `<MARCEL_ZOO_DIR>/integrations/news/feeds.yaml` and add or remove
   sources.
4. Restart Marcel (`request_restart()`). The scheduler will pick up the
   declarative `scheduled_jobs:` entry and start syncing twice daily.

### What becomes available after setup

- **news.sync** — fetches every configured feed, deduplicates, stores new
  articles
- **news.recent** — most recent articles, optionally filtered by source or
  topic
- **news.search** — keyword search across stored titles and descriptions

Tell the user these steps clearly and offer to help them through the
process.
