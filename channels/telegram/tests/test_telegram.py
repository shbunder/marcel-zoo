"""Tests for Telegram channel integration.

Covers bot.py (escape helpers), sessions.py (state management),
and webhook.py (routing, /start, /forget commands).
"""

import asyncio
import json

import respx
from fastapi.testclient import TestClient
from httpx import Response

from marcel_core.channels.telegram import sessions
from marcel_core.channels.telegram.bot import escape_markdown_v2
from marcel_core.config import settings
from marcel_core.harness.runner import TextDelta
from marcel_core.main import app
from marcel_core.storage import _root

# ---------------------------------------------------------------------------
# bot.py — escape helpers
# ---------------------------------------------------------------------------


class TestEscapeMarkdownV2:
    def test_escapes_all_special_chars(self):
        """All MarkdownV2 special characters are backslash-escaped."""
        result = escape_markdown_v2('_*[]()~`>#+-=|{}.!\\')
        # Every special char should be preceded by a backslash
        assert result.count('\\') >= len('_*[]()~`>#+-=|{}.!\\')

    def test_individual_special_chars(self):
        """Spot-check individual characters commonly seen in messages."""
        assert escape_markdown_v2('hello.') == r'hello\.'
        assert escape_markdown_v2('hi!') == r'hi\!'
        assert escape_markdown_v2('(ok)') == r'\(ok\)'
        assert escape_markdown_v2('some_name') == r'some\_name'

    def test_plain_text_and_empty_unchanged(self):
        assert escape_markdown_v2('hello world') == 'hello world'
        assert escape_markdown_v2('') == ''


# ---------------------------------------------------------------------------
# sessions.py — state management (simplified: no more conversation IDs)
# ---------------------------------------------------------------------------


class TestGetUserSlug:
    def test_returns_slug_for_known_chat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('shaun', 123456789)
        assert sessions.get_user_slug(123456789) == 'shaun'

    def test_returns_slug_with_string_chat_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('shaun', '123456789')
        assert sessions.get_user_slug('123456789') == 'shaun'

    def test_returns_none_for_unknown_chat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('shaun', 123456789)
        assert sessions.get_user_slug(999) is None

    def test_handles_multiple_users(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('alice', 111)
        sessions.link_user('bob', 222)
        assert sessions.get_user_slug(111) == 'alice'
        assert sessions.get_user_slug(222) == 'bob'

    def test_returns_none_when_no_users_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        assert sessions.get_user_slug(123) is None

    def test_ignores_user_dir_without_profile(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        (tmp_path / 'users' / 'shaun').mkdir(parents=True)
        assert sessions.get_user_slug(123) is None

    def test_link_user_writes_to_profile(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        sessions.link_user('shaun', 556632386)
        from marcel_core.storage.users import _parse_profile

        raw = (tmp_path / 'users' / 'shaun' / 'profile.md').read_text()
        meta, _ = _parse_profile(raw)
        assert meta['telegram_chat_id'] == '556632386'


class TestTouchLastMessage:
    def test_updates_channel_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        # Link user first so touch_last_message can resolve the slug
        sessions.link_user('shaun', 123)
        sessions.touch_last_message(123)
        from marcel_core.memory.conversation import load_channel_meta

        meta = load_channel_meta('shaun', 'telegram')
        assert meta is not None
        assert meta.last_active is not None

    def test_noop_for_unknown_chat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        # Should not raise for an unlinked chat
        sessions.touch_last_message(999)


# ---------------------------------------------------------------------------
# webhook.py — HTTP endpoint
# ---------------------------------------------------------------------------


def _make_update(chat_id: int, text: str) -> dict:
    return {
        'update_id': 1,
        'message': {
            'message_id': 1,
            'chat': {'id': chat_id, 'type': 'private'},
            'from': {'id': chat_id, 'is_bot': False, 'first_name': 'Shaun'},
            'text': text,
        },
    }


def _mock_stream(monkeypatch, tokens: list[str]) -> None:
    async def fake_stream(*args, **kwargs):
        for t in tokens:
            yield TextDelta(text=t)

    monkeypatch.setattr('marcel_core.channels.telegram.webhook.stream_turn', fake_stream)
    monkeypatch.setattr(
        'marcel_core.channels.telegram.webhook.extract_and_save_memories',
        lambda *a, **k: asyncio.sleep(0),
    )


_WEBHOOK_HEADERS = {'x-telegram-bot-api-secret-token': 'test-secret'}


class TestTelegramWebhook:
    def test_rejects_missing_webhook_secret(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        # No TELEGRAM_WEBHOOK_SECRET set — should reject
        client = TestClient(app)
        resp = client.post('/telegram/webhook', json={'update_id': 1})
        assert resp.status_code == 503

    def test_ignores_update_without_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        client = TestClient(app)
        resp = client.post('/telegram/webhook', json={'update_id': 1}, headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ignored'}

    def test_ignores_empty_text(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        update = _make_update(123, '')
        update['message']['text'] = ''
        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=update, headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ignored'}

    @respx.mock
    def test_start_command_sends_chat_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')

        sent_payload = {}

        def capture(request):
            sent_payload.update(json.loads(request.content))
            return Response(200, json={'ok': True})

        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(side_effect=capture)

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=_make_update(42, '/start'), headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}
        assert '42' in sent_payload.get('text', '')

    @respx.mock
    def test_unlinked_chat_sends_explanation(self, tmp_path, monkeypatch):
        # No telegram.json written for any user — chat is unlinked
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')

        sent_payload = {}

        def capture(request):
            sent_payload.update(json.loads(request.content))
            return Response(200, json={'ok': True})

        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(side_effect=capture)

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=_make_update(99, 'hello'), headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}
        assert '99' in sent_payload.get('text', '')

    def test_rejects_bad_webhook_secret(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'my-secret')

        client = TestClient(app)
        resp = client.post(
            '/telegram/webhook',
            json=_make_update(1, 'hi'),
            headers={'x-telegram-bot-api-secret-token': 'wrong'},
        )
        assert resp.status_code == 403

    def test_accepts_correct_webhook_secret(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'my-secret')
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')

        with respx.mock:
            respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
                return_value=Response(200, json={'ok': True})
            )
            client = TestClient(app)
            resp = client.post(
                '/telegram/webhook',
                json=_make_update(1, 'hi'),
                headers={'x-telegram-bot-api-secret-token': 'my-secret'},
            )
        assert resp.status_code == 200

    @respx.mock
    def test_linked_chat_dispatches_to_agent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        sessions.link_user('shaun', 555)
        _mock_stream(monkeypatch, ['Hello', ' Shaun'])

        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(200, json={'ok': True})
        )

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=_make_update(555, 'hi'), headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}


class TestForgetCommand:
    @respx.mock
    def test_forget_command_responds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        sessions.link_user('shaun', 555)

        # No active content — should reply "nothing to compress"
        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(200, json={'ok': True})
        )

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=_make_update(555, '/forget'), headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}

    @respx.mock
    def test_new_command_acts_as_forget(self, tmp_path, monkeypatch):
        """The /new command should behave identically to /forget."""
        monkeypatch.setattr(_root, '_DATA_ROOT', tmp_path)
        monkeypatch.setattr(settings, 'telegram_bot_token', 'test-token')
        monkeypatch.setattr(settings, 'telegram_webhook_secret', 'test-secret')
        sessions.link_user('shaun', 555)

        respx.post('https://api.telegram.org/bottest-token/sendMessage').mock(
            return_value=Response(200, json={'ok': True})
        )

        client = TestClient(app)
        resp = client.post('/telegram/webhook', json=_make_update(555, '/new'), headers=_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}
