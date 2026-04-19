"""Scenario-based tests for telegram/bot.py HTTP operations.

Covers: send_message, edit_message_text, send_photo, answer_callback_query,
set_webhook, delete_webhook, set_menu_button with mocked httpx responses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_token():
    with patch('marcel_core.channels.telegram.bot.settings') as mock_settings:
        mock_settings.telegram_bot_token = 'test-token'
        mock_settings.marcel_public_url = 'https://marcel.app'
        yield


def _mock_response(success: bool = True, data: dict | None = None):
    resp = MagicMock()
    resp.is_success = success
    resp.status_code = 200 if success else 400
    resp.text = 'error'
    resp.json.return_value = data or {'result': {'message_id': 42}}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(responses: list[MagicMock]):
    """Create a mock httpx.AsyncClient that returns responses in sequence."""
    client = AsyncMock()
    client.post = AsyncMock(side_effect=responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_success(self):
        from marcel_core.channels.telegram.bot import send_message

        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            msg_id = await send_message(123, '<b>Hello</b>')
        assert msg_id == 42

    @pytest.mark.asyncio
    async def test_html_rejected_falls_back_to_plain(self):
        from marcel_core.channels.telegram.bot import send_message

        client = _mock_client([_mock_response(False), _mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            msg_id = await send_message(123, '<b>bad html</b>')
        assert msg_id == 42
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_both_attempts_fail(self):
        from marcel_core.channels.telegram.bot import send_message

        fail_resp = _mock_response(False)
        client = _mock_client([fail_resp, fail_resp])
        with (
            patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client),
            pytest.raises(RuntimeError, match='sendMessage failed'),
        ):
            await send_message(123, 'text')

    @pytest.mark.asyncio
    async def test_with_reply_markup(self):
        from marcel_core.channels.telegram.bot import send_message

        client = _mock_client([_mock_response(True)])
        markup = {'inline_keyboard': [[{'text': 'Click', 'callback_data': 'test'}]]}
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            await send_message(123, 'text', reply_markup=markup)
        payload = client.post.call_args[1]['json']
        assert 'reply_markup' in payload


class TestEditMessageText:
    @pytest.mark.asyncio
    async def test_success(self):
        from marcel_core.channels.telegram.bot import edit_message_text

        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await edit_message_text(123, 1, '<b>Updated</b>')
        assert result is True

    @pytest.mark.asyncio
    async def test_html_fallback(self):
        from marcel_core.channels.telegram.bot import edit_message_text

        client = _mock_client([_mock_response(False), _mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await edit_message_text(123, 1, '<b>bad</b>')
        assert result is True

    @pytest.mark.asyncio
    async def test_both_fail(self):
        from marcel_core.channels.telegram.bot import edit_message_text

        client = _mock_client([_mock_response(False), _mock_response(False)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await edit_message_text(123, 1, 'text')
        assert result is False


class TestSendPhoto:
    @pytest.mark.asyncio
    async def test_send_bytes(self):
        from marcel_core.channels.telegram.bot import send_photo

        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            msg_id = await send_photo(123, b'fakepng', caption='Chart')
        assert msg_id == 42

    @pytest.mark.asyncio
    async def test_send_url(self):
        from marcel_core.channels.telegram.bot import send_photo

        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            msg_id = await send_photo(123, 'https://example.com/photo.jpg')
        assert msg_id == 42

    @pytest.mark.asyncio
    async def test_send_photo_failure(self):
        from marcel_core.channels.telegram.bot import send_photo

        client = _mock_client([_mock_response(False)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            msg_id = await send_photo(123, b'png')
        assert msg_id is None

    @pytest.mark.asyncio
    async def test_bytes_with_markup(self):
        from marcel_core.channels.telegram.bot import send_photo

        markup = {'inline_keyboard': []}
        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            await send_photo(123, b'png', caption='Cap', reply_markup=markup)


class TestAnswerCallbackQuery:
    @pytest.mark.asyncio
    async def test_answer(self):
        from marcel_core.channels.telegram.bot import answer_callback_query

        client = _mock_client([_mock_response(True)])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            await answer_callback_query('q1', text='Done')


class TestSetWebhook:
    @pytest.mark.asyncio
    async def test_set_webhook(self):
        from marcel_core.channels.telegram.bot import set_webhook

        client = _mock_client([_mock_response(True, {'ok': True})])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await set_webhook('https://example.com/webhook', secret='sec')
        assert result == {'ok': True}


class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        from marcel_core.channels.telegram.bot import delete_webhook

        client = _mock_client([_mock_response(True, {'ok': True})])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await delete_webhook()
        assert result == {'ok': True}


class TestSetMenuButton:
    @pytest.mark.asyncio
    async def test_set_menu_button(self):
        from marcel_core.channels.telegram.bot import set_menu_button

        client = _mock_client([_mock_response(True, {'ok': True})])
        with patch('marcel_core.channels.telegram.bot.httpx.AsyncClient', return_value=client):
            result = await set_menu_button()
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_public_url(self):
        from marcel_core.channels.telegram.bot import set_menu_button

        with patch('marcel_core.channels.telegram.bot._public_url', return_value=None):
            result = await set_menu_button()
        assert result is None
