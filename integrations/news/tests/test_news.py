"""Unit tests for the news habitat — cache + sync.

Tests load ``cache.py`` and ``sync.py`` directly via ``importlib`` rather
than importing the parent package, because importing ``__init__.py`` would
re-trigger ``@register`` and collide on the kernel's global integration
registry. The handlers in ``__init__.py`` are three-line wrappers over
cache + sync; they are exercised end-to-end by the kernel's discovery +
dispatch tests in the Marcel repo (``tests/skills/test_news_habitat.py``).

A per-test ``tmp_path`` is wired into :mod:`marcel_core.storage._root` so
the SQLite DB lands in an isolated directory.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from marcel_core.storage import _root

_HABITAT_DIR = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, filename: str) -> Any:
    path = _HABITAT_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cache = _load('_news_cache_under_test', 'cache.py')
sync = _load('_news_sync_under_test', 'sync.py')

# sync.py imports cache via relative ``from . import cache`` — rewire its
# reference to the same module we loaded so both files share one sqlite path.
sync.cache = cache


@pytest.fixture(autouse=True)
def _isolate(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)


# ---------------------------------------------------------------------------
# Cache layer (direct)
# ---------------------------------------------------------------------------


class TestNewsCache:
    def test_upsert_and_query(self) -> None:
        articles = [
            {
                'title': 'AI Boom',
                'source': 'VRT NWS',
                'link': 'https://vrt.be/1',
                'topic': 'Tech',
                'description': 'AI is booming',
            },
            {
                'title': 'Markets Up',
                'source': 'De Tijd',
                'link': 'https://tijd.be/1',
                'topic': 'Finance',
                'description': 'Markets rally',
            },
        ]
        count = cache.upsert_articles('alice', articles)
        assert count == 2

        all_articles = cache.get_articles('alice')
        assert len(all_articles) == 2

    def test_upsert_deduplication(self) -> None:
        article = [{'title': 'Same', 'source': 'VRT', 'link': 'https://vrt.be/same', 'topic': 'Tech'}]
        cache.upsert_articles('alice', article)
        cache.upsert_articles('alice', article)

        all_articles = cache.get_articles('alice')
        assert len(all_articles) == 1

    def test_upsert_skips_no_link(self) -> None:
        count = cache.upsert_articles('alice', [{'title': 'No Link', 'source': 'VRT'}])
        assert count == 0

    def test_upsert_uses_url_field(self) -> None:
        articles = [{'title': 'URL field', 'source': 'VRT', 'url': 'https://vrt.be/url-field'}]
        count = cache.upsert_articles('alice', articles)
        assert count == 1
        assert cache.get_articles('alice')[0]['link'] == 'https://vrt.be/url-field'

    def test_filter_by_source(self) -> None:
        cache.upsert_articles(
            'alice',
            [
                {'title': 'A', 'source': 'VRT', 'link': 'https://vrt.be/a'},
                {'title': 'B', 'source': 'Tijd', 'link': 'https://tijd.be/b'},
            ],
        )
        results = cache.get_articles('alice', source='VRT')
        assert len(results) == 1
        assert results[0]['source'] == 'VRT'

    def test_filter_by_topic(self) -> None:
        cache.upsert_articles(
            'alice',
            [
                {'title': 'A', 'source': 'VRT', 'link': 'https://1', 'topic': 'Tech'},
                {'title': 'B', 'source': 'VRT', 'link': 'https://2', 'topic': 'Sports'},
            ],
        )
        assert len(cache.get_articles('alice', topic='Tech')) == 1

    def test_keyword_search(self) -> None:
        cache.upsert_articles(
            'alice',
            [
                {
                    'title': 'AI Revolution',
                    'source': 'VRT',
                    'link': 'https://1',
                    'description': 'Artificial intelligence',
                },
                {'title': 'Weather', 'source': 'VRT', 'link': 'https://2', 'description': 'Rain tomorrow'},
            ],
        )
        results = cache.get_articles('alice', search='Revolution')
        assert len(results) == 1
        assert results[0]['title'] == 'AI Revolution'

    def test_date_filters(self) -> None:
        cache.upsert_articles(
            'alice',
            [
                {'title': 'Old', 'source': 'VRT', 'link': 'https://1'},
                {'title': 'New', 'source': 'VRT', 'link': 'https://2'},
            ],
        )
        assert len(cache.get_articles('alice')) == 2
        assert len(cache.get_articles('alice', date_from='2020-01-01', date_to='2099-12-31')) == 2

    def test_limit(self) -> None:
        arts = [{'title': f'Art {i}', 'source': 'VRT', 'link': f'https://vrt.be/{i}'} for i in range(10)]
        cache.upsert_articles('alice', arts)
        assert len(cache.get_articles('alice', limit=3)) == 3

    def test_filter_new_links(self) -> None:
        cache.upsert_articles('alice', [{'title': 'Existing', 'source': 'VRT', 'link': 'https://vrt.be/exists'}])
        new = cache.filter_new_links('alice', ['https://vrt.be/exists', 'https://vrt.be/new'])
        assert new == ['https://vrt.be/new']

    def test_filter_new_links_empty(self) -> None:
        assert cache.filter_new_links('alice', []) == []

    def test_article_id_stable(self) -> None:
        assert cache.article_id('https://vrt.be/1') == cache.article_id('https://vrt.be/1')
        assert cache.article_id('https://vrt.be/1') != cache.article_id('https://vrt.be/2')


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


class TestNewsSync:
    @pytest.mark.asyncio
    async def test_sync_feeds_stores_new_articles(self) -> None:
        feed_config = [
            {
                'name': 'Test Source',
                'feeds': ['https://example.com/feed.xml'],
                'exclude_categories': [],
            }
        ]
        mock_articles = [
            {'title': 'Article 1', 'link': 'https://example.com/1', 'category': 'Tech', 'description': 'Desc 1'},
            {'title': 'Article 2', 'link': 'https://example.com/2', 'category': 'Finance', 'description': 'Desc 2'},
        ]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = mock_articles
            result = await sync.sync_feeds('alice')

        assert result['new'] == 2
        assert result['total_fetched'] == 2

        stored = cache.get_articles('alice')
        assert len(stored) == 2
        assert stored[0]['source'] == 'Test Source'

    @pytest.mark.asyncio
    async def test_sync_feeds_deduplicates(self) -> None:
        feed_config = [
            {'name': 'Source A', 'feeds': ['https://a.com/feed1.xml', 'https://a.com/feed2.xml']},
        ]
        same_article = [{'title': 'Same Article', 'link': 'https://a.com/same', 'category': 'Tech'}]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = same_article
            result = await sync.sync_feeds('alice')

        assert result['new'] == 1
        assert result['unique'] == 1

    @pytest.mark.asyncio
    async def test_sync_feeds_skips_known_articles(self) -> None:
        cache.upsert_articles('alice', [{'title': 'Old', 'source': 'VRT', 'link': 'https://vrt.be/old'}])

        feed_config = [{'name': 'VRT', 'feeds': ['https://vrt.be/feed.xml']}]
        articles = [
            {'title': 'Old', 'link': 'https://vrt.be/old'},
            {'title': 'New', 'link': 'https://vrt.be/new'},
        ]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = articles
            result = await sync.sync_feeds('alice')

        assert result['new'] == 1

    @pytest.mark.asyncio
    async def test_sync_feeds_excludes_categories(self) -> None:
        feed_config = [
            {
                'name': 'VRT NWS',
                'feeds': ['https://vrt.be/feed.xml'],
                'exclude_categories': ['sport', 'weer'],
            }
        ]
        articles = [
            {'title': 'News', 'link': 'https://vrt.be/news', 'category': 'binnenland'},
            {'title': 'Sport', 'link': 'https://vrt.be/sport', 'category': 'Sport'},
            {'title': 'Weather', 'link': 'https://vrt.be/weer', 'category': 'Weer'},
        ]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = articles
            result = await sync.sync_feeds('alice')

        assert result['new'] == 1

    @pytest.mark.asyncio
    async def test_sync_feeds_handles_fetch_error(self) -> None:
        feed_config = [
            {'name': 'Broken', 'feeds': ['https://broken.com/feed.xml']},
            {'name': 'Working', 'feeds': ['https://working.com/feed.xml']},
        ]

        async def mock_fetch(url: str, max_articles: int = 50) -> list[dict[str, str]]:
            if 'broken' in url:
                raise ConnectionError('DNS failed')
            return [{'title': 'Works', 'link': 'https://working.com/1', 'category': 'Tech'}]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', side_effect=mock_fetch),
        ):
            result = await sync.sync_feeds('alice')

        assert result['new'] == 1

    @pytest.mark.asyncio
    async def test_sync_feeds_skips_non_xml_response(self) -> None:
        """A feed that returns HTML raises ``ValueError`` in the fetcher;
        the sync loop should log one line and move on, not crash."""
        feed_config = [{'name': 'Dead', 'feeds': ['https://dead.example/feed']}]

        async def mock_fetch(url: str, max_articles: int = 50) -> list[dict[str, str]]:
            raise ValueError("feed did not return XML (starts with: '<!doctype html>')")

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', side_effect=mock_fetch),
        ):
            result = await sync.sync_feeds('alice')

        assert result['new'] == 0
        assert result['total_fetched'] == 0

    @pytest.mark.asyncio
    async def test_sync_feeds_no_sources(self) -> None:
        with patch.object(sync, 'load_feed_config', return_value=[]):
            result = await sync.sync_feeds('alice')

        assert result['new'] == 0
        assert 'error' in result

    def test_load_feed_config_reads_bundled_yaml(self) -> None:
        sources = sync.load_feed_config()
        assert len(sources) > 0
        assert sources[0]['name'] == 'VRT NWS'
        assert len(sources[0]['feeds']) > 0

    @pytest.mark.asyncio
    async def test_sync_feeds_maps_category_to_topic(self) -> None:
        feed_config = [{'name': 'Test', 'feeds': ['https://test.com/feed.xml']}]
        articles = [{'title': 'Art', 'link': 'https://test.com/1', 'category': 'Politiek'}]

        with (
            patch.object(sync, 'load_feed_config', return_value=feed_config),
            patch.object(sync, 'fetch_feed', new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = articles
            await sync.sync_feeds('alice')

        stored = cache.get_articles('alice')
        assert stored[0]['topic'] == 'Politiek'


