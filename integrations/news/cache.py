"""SQLite-backed article cache for the news habitat.

The cache lives at ``<cache_dir>/news.db`` (resolved via
:func:`marcel_core.plugin.paths.cache_dir`) and stores every scraped
article with structured metadata so it can be queried by source, topic,
date, or keyword.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marcel_core.plugin import get_logger, paths

log = get_logger(__name__)


def _db_path(slug: str) -> Path:
    return paths.cache_dir(slug) / 'news.db'


def _connect(slug: str) -> sqlite3.Connection:
    path = _db_path(slug)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            source        TEXT NOT NULL,
            link          TEXT NOT NULL,
            topic         TEXT,
            description   TEXT,
            published_at  TEXT,
            scraped_at    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_articles_source
            ON articles(source);
        CREATE INDEX IF NOT EXISTS idx_articles_topic
            ON articles(topic);
        CREATE INDEX IF NOT EXISTS idx_articles_published
            ON articles(published_at);
    """)


def article_id(link: str) -> str:
    """Derive a stable unique ID from an article URL."""
    return hashlib.sha256(link.encode()).hexdigest()[:16]


# -- Write operations --------------------------------------------------------


def upsert_articles(slug: str, articles: list[dict[str, Any]]) -> int:
    """Upsert articles into the cache.  Returns count of new/updated rows."""
    conn = _connect(slug)
    now = datetime.now(UTC).isoformat()
    count = 0
    try:
        for art in articles:
            link = art.get('link') or art.get('url', '')
            if not link:
                log.warning('[news-cache] Skipping article without link: %s', art.get('title', '?'))
                continue
            aid = article_id(link)
            conn.execute(
                """INSERT INTO articles
                   (id, title, source, link, topic, description, published_at, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       title = excluded.title,
                       source = excluded.source,
                       topic = excluded.topic,
                       description = excluded.description,
                       published_at = excluded.published_at,
                       scraped_at = excluded.scraped_at
                """,
                (
                    aid,
                    art.get('title', ''),
                    art.get('source', ''),
                    link,
                    art.get('topic', art.get('category', '')),
                    art.get('description', art.get('summary', '')),
                    art.get('published_at', ''),
                    now,
                ),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    log.info('[news-cache] Upserted %d articles for user=%s', count, slug)
    return count


def filter_new_links(slug: str, links: list[str]) -> list[str]:
    """Return only the links that are NOT already in the database."""
    if not links:
        return []
    conn = _connect(slug)
    try:
        ids = [article_id(link) for link in links]
        placeholders = ','.join('?' for _ in ids)
        existing = {
            row[0] for row in conn.execute(f'SELECT id FROM articles WHERE id IN ({placeholders})', ids).fetchall()
        }
        return [link for link, aid in zip(links, ids) if aid not in existing]
    finally:
        conn.close()


# -- Read operations ----------------------------------------------------------


def get_articles(
    slug: str,
    *,
    source: str | None = None,
    topic: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query cached articles with optional filters.

    Returns a list of dicts ordered by scraped_at descending.
    """
    conn = _connect(slug)
    try:
        clauses: list[str] = []
        params: list[Any] = []

        if source:
            clauses.append('source = ?')
            params.append(source)
        if topic:
            clauses.append('topic = ?')
            params.append(topic)
        if date_from:
            clauses.append('scraped_at >= ?')
            params.append(date_from)
        if date_to:
            clauses.append('scraped_at <= ?')
            params.append(date_to)
        if search:
            clauses.append('(title LIKE ? OR description LIKE ?)')
            pattern = f'%{search}%'
            params.extend([pattern, pattern])

        where = f'WHERE {" AND ".join(clauses)}' if clauses else ''
        query = f'SELECT * FROM articles {where} ORDER BY scraped_at DESC LIMIT ?'
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
