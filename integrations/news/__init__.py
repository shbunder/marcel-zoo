"""News integration — RSS feed sync, storage, and retrieval.

Registers ``news.sync``, ``news.search``, and ``news.recent`` as plugin
integration handlers. Articles are stored per-user in a SQLite database
at ``<cache_dir>/news.db`` (resolved via :mod:`marcel_core.plugin.paths`).

``news.sync`` is the target of a declarative ``scheduled_jobs:`` entry in
``integration.yaml`` — the scheduler invokes it with ``user_slug='_system'``
twice a day. On that sentinel, the handler iterates every live user slug
on disk and syncs each one; when called directly with a real slug (e.g.
via the ``integration`` tool), it syncs just that user.
"""

from __future__ import annotations

import json
import re

from marcel_core.plugin import get_logger, paths, register

from . import cache

log = get_logger(__name__)

_SYSTEM_USER = '_system'
_BACKUP_SLUG_RE = re.compile(r'\.backup-\d')


def _live_user_slugs() -> list[str]:
    """Return the slugs the sync job should touch — every on-disk user minus
    backup snapshots and the ``_system`` sentinel itself.
    """
    return sorted(
        slug for slug in paths.list_user_slugs() if slug != _SYSTEM_USER and not _BACKUP_SLUG_RE.search(slug)
    )


@register('news.sync')
async def sync(params: dict, user_slug: str) -> str:
    """Fetch all configured RSS feeds, deduplicate, and store new articles.

    When ``user_slug == '_system'`` (the scheduler's system-scope dispatch),
    iterate every live user and sync each. When a real slug is passed,
    sync only that user.

    No parameters required — feed URLs are loaded from ``feeds.yaml`` next
    to this module.
    """
    from .sync import sync_feeds

    if user_slug != _SYSTEM_USER:
        summary = await sync_feeds(user_slug)
        return json.dumps(summary, indent=2)

    slugs = _live_user_slugs()
    if not slugs:
        return json.dumps({'users': [], 'new': 0, 'note': 'no live users on disk'}, indent=2)

    per_user: list[dict] = []
    total_new = 0
    for slug in slugs:
        try:
            summary = await sync_feeds(slug)
        except Exception as exc:
            log.warning('[news-sync] user=%s failed: %s', slug, exc)
            per_user.append({'user': slug, 'error': str(exc)})
            continue
        total_new += int(summary.get('new', 0))
        per_user.append({'user': slug, **summary})

    return json.dumps({'users': per_user, 'new_total': total_new}, indent=2)


@register('news.search')
async def search(params: dict, user_slug: str) -> str:
    """Query stored articles with optional filters.

    All parameters are optional:
    - ``source``: filter by news source (e.g. "VRT NWS", "De Tijd")
    - ``topic``: filter by topic/category
    - ``date_from`` / ``date_to``: ISO date range
    - ``search``: keyword search in title and description
    - ``limit``: max results (default 50)
    """
    limit = int(params.get('limit', '50'))
    rows = cache.get_articles(
        user_slug,
        source=params.get('source'),
        topic=params.get('topic'),
        date_from=params.get('date_from'),
        date_to=params.get('date_to'),
        search=params.get('search'),
        limit=limit,
    )
    return json.dumps({'articles': rows, 'count': len(rows)}, indent=2)


@register('news.recent')
async def recent(params: dict, user_slug: str) -> str:
    """Get the most recent articles, optionally filtered by source or topic."""
    limit = int(params.get('limit', '20'))
    rows = cache.get_articles(
        user_slug,
        source=params.get('source'),
        topic=params.get('topic'),
        limit=limit,
    )
    return json.dumps({'articles': rows, 'count': len(rows)}, indent=2)
